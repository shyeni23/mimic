import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiSparklingLine, RiHeartLine, RiHeartFill,
  RiAddLine, RiStarFill, RiShieldCheckLine,
  RiPaletteLine, RiRulerLine, RiErrorWarningLine,
  RiLoader4Line,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import FilterChips from '../components/Common/FilterChips';
import { useSession } from '../context/SessionContext';
import { apiPostJSON, apiGetJSON } from '../utils/api';
import { logEvent, logEventNow } from '../hooks/useEventLogger';
import { mapBodyShape, mapSkinDepth, mapUndertone } from '../utils/mapBackendValues';
import './Recommendations.css';

const categories = ['All', 'Tops', 'Bottoms', 'Dresses', 'Shoes', 'Bags', 'Watches', 'Jewellery', 'Accessories'];
// Real occasion tags actually present in inventory (see /api/inventory/occasions)
// -- fetched at mount rather than hardcoded here, same reasoning as the
// backend route's own docstring: don't guess a list that might not match
// what's really tagged.
const DEFAULT_OCCASIONS = ['All'];

// "What should I include?" -- the on-screen version of the question Aria asks
// in chat. Each chip maps to the inventory categories the backend builds; an
// empty selection means the full look. Clothes is one chip because a customer
// says "just clothes", not "tops, bottoms and dresses".
const INCLUDE_OPTIONS = [
  { key: 'clothes', label: 'Clothes', categories: ['top', 'bottom', 'dress'] },
  { key: 'footwear', label: 'Footwear & Heels', categories: ['footwear'] },
  { key: 'bag', label: 'Bags', categories: ['bag'] },
  { key: 'watch', label: 'Watches', categories: ['watch'] },
  { key: 'jewelry', label: 'Jewellery', categories: ['jewelry'] },
  { key: 'accessory', label: 'Accessories', categories: ['accessory'] },
];

const EMOJI_BY_CATEGORY = {
  top: '👕', bottom: '👖', dress: '👗', footwear: '👟', bag: '👜',
  accessory: '🕶️', watch: '⌚', jewelry: '💎',
};
const GRADIENT_BY_CATEGORY = {
  top: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  bottom: 'linear-gradient(135deg, #434343 0%, #000000 100%)',
  dress: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
  footwear: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
  bag: 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)',
  accessory: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
};

function normalizeProduct(item, index) {
  const cat = (item.category || '').toLowerCase();
  return {
    id: item.id || index,
    name: item.name || 'Unknown Item',
    brand: item.brand || '',
    price: item.price || 0,
    size: item.size || '—',
    color: item.color || '—',
    category: item.category || 'Tops',
    emoji: EMOJI_BY_CATEGORY[cat] || '🧥',
    gradient: GRADIENT_BY_CATEGORY[cat] || 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    confidence: item.similarity ? Math.round(item.similarity * 100) : 80,
    reason: item.explanation || 'AI-recommended based on your style profile.',
    image_url: item.image_url || null,
  };
}

function normalizeSection(sec) {
  return {
    ...sec,
    items: (sec.items || []).map(normalizeProduct),
    groups: Array.isArray(sec.groups)
      ? sec.groups.map((g) => ({ ...g, items: (g.items || []).map(normalizeProduct) }))
      : null,
  };
}

export default function Recommendations() {
  const {
    sessionId, scanData, setScanData,
    pendingRecommendations, setPendingRecommendations,
    highlightedItemId, setHighlightedItemId,
    fireAgentEvent,
  } = useSession();
  const [activeFilter, setActiveFilter] = useState('All');
  const [occasions, setOccasions] = useState(DEFAULT_OCCASIONS);
  const [activeOccasion, setActiveOccasion] = useState('All');
  const [favorites, setFavorites] = useState({});
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // What the backend says it actually derived the picks from -- the scan row
  // /api/recommend read, not the frontend's copy of the scan response.
  // Shown as a "Based on your scan" strip so scan -> picks is visible, not
  // implied. Falls back to scanData (same fields, different key names) when
  // the products came from Aria's tool call rather than this page's fetch.
  const [scanProfile, setScanProfile] = useState(null);
  // Complete-look sections from /api/recommend?grouped (or from Aria's
  // show_recommendations payload). null = flat list mode.
  const [sections, setSections] = useState(null);
  // Which item types the customer wants. Empty = everything (the full look).
  // Clothes first -- accessories are offered once she likes a piece
  // (item_liked -> Aria asks -> complete_outfit). Reset = the full look.
  const [includeKeys, setIncludeKeys] = useState(['clothes']);

  const fetchRecommendations = useCallback(async (category, occasion, includeSel) => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const body = { session_id: sessionId };
      if (category && category !== 'All') {
        body.category = category.toLowerCase();
      } else {
        // "All" after a scan = the complete look: what suits this body plus
        // the footwear / bag / watch / jewellery / accessories that finish it.
        body.grouped = true;
      }
      if (occasion && occasion !== 'All') {
        body.occasion = occasion.toLowerCase();
        // The customer picked this occasion, so it's a requirement, not a
        // hint: the backend hard-filters every group to it.
        body.strict_occasion = true;
      }
      const chosen = (includeSel || []).flatMap(
        (k) => (INCLUDE_OPTIONS.find((o) => o.key === k) || {}).categories || [],
      );
      if (chosen.length > 0) body.include = chosen;
      const data = await apiPostJSON('/api/recommend', body);
      setProducts((data.results || []).map(normalizeProduct));
      setSections(Array.isArray(data.sections) ? data.sections.map(normalizeSection) : null);
      if (data.scan_profile) setScanProfile(data.scan_profile);
    } catch (err) {
      setError(err.message);
      setProducts([]);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGetJSON('/api/inventory/occasions');
        setOccasions(['All', ...(data.occasions || [])]);
      } catch {
        setOccasions(DEFAULT_OCCASIONS);
      }
    })();
  }, []);

  // Phase B (Module 2): if the chat agent already fetched results via its
  // recommend_clothes tool and queued a show_recommendations action, use
  // those directly instead of re-fetching -- avoids a redundant API call and
  // shows exactly what Aria referenced in her reply.
  useEffect(() => {
    if (pendingRecommendations) {
      const payload = Array.isArray(pendingRecommendations)
        ? { results: pendingRecommendations }
        : pendingRecommendations;
      setProducts((payload.results || []).map(normalizeProduct));
      const hasSections = Array.isArray(payload.sections) && payload.sections.length > 0;
      setSections(hasSections ? payload.sections.map(normalizeSection) : null);
      if (hasSections) setActiveFilter('All');
      // Aria asked "what should I include?" and the customer answered her --
      // reflect that answer in the chips instead of leaving them showing
      // "everything" next to a narrowed result.
      if (Array.isArray(payload.requested_categories)) {
        const keys = INCLUDE_OPTIONS
          .filter((o) => o.categories.some((c) => payload.requested_categories.includes(c)))
          .map((o) => o.key);
        setIncludeKeys(keys);
      }
      setPendingRecommendations(null);
    }
  }, [pendingRecommendations, setPendingRecommendations]);

  useEffect(() => {
    if (sessionId && scanData && !pendingRecommendations) {
      fetchRecommendations(activeFilter, activeOccasion, includeKeys);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, scanData, activeFilter, activeOccasion, includeKeys, fetchRecommendations]);

  // New customer (presence reset -> resetSession clears scanData): drop the
  // previous person's profile strip rather than showing it over "Run a body
  // scan first".
  useEffect(() => {
    if (!scanData) setScanProfile(null);
  }, [scanData]);

  // Clear the highlight once it's been shown for a bit -- otherwise the same
  // item stays visually pinned on every later visit to this page. Right
  // before clearing, let Aria proactively comment on it (item_focused_long).
  useEffect(() => {
    if (!highlightedItemId) return;
    const timer = setTimeout(() => {
      fireAgentEvent('item_focused_long');
      setHighlightedItemId(null);
    }, 5000);
    return () => clearTimeout(timer);
  }, [highlightedItemId, setHighlightedItemId, fireAgentEvent]);

  // Proactive agent event: if the customer just sits on this page without
  // touching anything (no filter change, no favorite, no add-to-outfit) for
  // a while, let Aria check in instead of waiting to be asked.
  const IDLE_THRESHOLD_MS = 25000;
  const lastInteractionRef = useRef(Date.now());
  const idleFiredRef = useRef(false);

  const markInteraction = useCallback(() => {
    lastInteractionRef.current = Date.now();
    idleFiredRef.current = false;
  }, []);

  useEffect(() => {
    if (!sessionId || products.length === 0) return undefined;
    const interval = setInterval(() => {
      if (idleFiredRef.current) return;
      if (Date.now() - lastInteractionRef.current >= IDLE_THRESHOLD_MS) {
        idleFiredRef.current = true;
        fireAgentEvent('recommendations_idle');
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [sessionId, products.length, fireAgentEvent]);

  const dismissCountRef = useRef(0);
  const skippedFiredRef = useRef(false);

  // Tell Aria she liked a piece so she can offer accessories for it.
  const likedFiredRef = useRef(new Set());
  const notifyLiked = (product) => {
    if (!product || !fireAgentEvent || likedFiredRef.current.has(product.id)) return;
    likedFiredRef.current.add(product.id);
    fireAgentEvent('item_liked', 'customer', {
      item_id: String(product.id), name: product.name, category: product.category,
    });
  };

  const toggleFavorite = (id, product) => {
    markInteraction();
    const willFavorite = !favorites[id];
    if (willFavorite) notifyLiked(product);
    setFavorites((prev) => ({ ...prev, [id]: !prev[id] }));
    logEventNow(sessionId, id, willFavorite ? 'click' : 'dismiss', {
      source: 'recommendations', action: 'favorite_toggle',
    });
    if (!willFavorite) {
      dismissCountRef.current += 1;
      // Fire once per set of recommendations after 3 dismisses -- Aria pivots.
      if (dismissCountRef.current >= 3 && !skippedFiredRef.current && fireAgentEvent) {
        skippedFiredRef.current = true;
        fireAgentEvent('skipped_multiple');
      }
    } else {
      dismissCountRef.current = 0;
    }
  };

  // Reset dismiss tracking when a new batch of recommendations loads.
  useEffect(() => {
    dismissCountRef.current = 0;
    skippedFiredRef.current = false;
  }, [products.length, activeFilter]);

  // Batch-log a per-item view for every recommendation shown to the customer,
  // plus a single recommend_shown event with the whole batch's ids. Together
  // these become the labeled data for the future user-tower training set.
  useEffect(() => {
    if (!sessionId || products.length === 0) return;
    products.forEach((p) => logEvent(sessionId, p.id, 'view', { source: 'recommendations' }));
    logEventNow(sessionId, null, 'recommend_shown', {
      item_ids: products.map((p) => p.id),
      filter: activeFilter,
    });
  }, [sessionId, products, activeFilter]);

  const noScan = !scanData;

  const renderCard = (product, index) => (
          <GlassCard
            key={product.id}
            className={`rec-product-card${String(product.id) === String(highlightedItemId) ? ' rec-product-highlighted' : ''}`}
            delay={index * 0.1}
          >
            <div
              className="rec-product-image"
              style={{ background: product.image_url ? `url(${product.image_url}) center/cover` : product.gradient }}
            >
              {!product.image_url && <span className="rec-product-emoji">{product.emoji}</span>}
              <div className="rec-confidence-badge">
                <RiShieldCheckLine />
                <span>{product.confidence}% Match</span>
              </div>
              <motion.button
                className={`rec-heart-btn ${favorites[product.id] ? 'active' : ''}`}
                onClick={() => toggleFavorite(product.id, product)}
                whileTap={{ scale: 0.8 }}
              >
                {favorites[product.id] ? <RiHeartFill /> : <RiHeartLine />}
              </motion.button>
            </div>

            <div className="rec-product-info">
              {product.brand && <div className="rec-product-brand">{product.brand}</div>}
              <h3 className="rec-product-name">{product.name}</h3>
              {product.price > 0 && (
                <div className="rec-product-price">
                  ${product.price.toLocaleString()}
                </div>
              )}

              <div className="rec-product-meta">
                <span className="rec-meta-tag">
                  <RiRulerLine /> {product.size}
                </span>
                <span className="rec-meta-tag">
                  <RiPaletteLine /> {product.color}
                </span>
              </div>

              <div className="rec-ai-reason">
                <div className="rec-reason-header">
                  <RiSparklingLine />
                  <span>Why AI picked this</span>
                </div>
                <p>{product.reason}</p>
              </div>

              <div className="rec-match-bar">
                <div className="rec-match-track">
                  <motion.div
                    className="rec-match-fill"
                    initial={{ width: 0 }}
                    animate={{ width: `${product.confidence}%` }}
                    transition={{ duration: 1, delay: 0.3 + index * 0.1 }}
                  />
                </div>
                <div className="rec-match-stars">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <RiStarFill
                      key={star}
                      className={
                        star <= Math.round(product.confidence / 20)
                          ? 'star-filled'
                          : 'star-empty'
                      }
                    />
                  ))}
                </div>
              </div>

              <AnimatedButton
                variant="primary"
                size="small"
                fullWidth
                icon={<RiAddLine />}
                onClick={() => {
                  markInteraction();
                  logEventNow(sessionId, product.id, 'add_to_cart', {
                    source: 'recommendations', action: 'add_to_outfit',
                  });
                  notifyLiked(product);
                }}
              >
                Add to Outfit
              </AnimatedButton>
            </div>
          </GlassCard>
  );

  // Post-scan "complete look": one headed row per category. Only when no
  // category chip is active -- a chip means the customer asked for one kind
  // of thing, so the flat grid is the right answer there.
  const showSections = activeFilter === 'All' && Array.isArray(sections) && sections.length > 0;

  // Merge the two shapes: /api/recommend's scan_profile (DB column names)
  // and /api/vision/scan's response (skin_tone_depth etc.).
  const profile = scanProfile || (scanData && {
    body_shape: scanData.body_shape,
    skin_tone_category: scanData.skin_tone_depth,
    skin_tone_undertone: scanData.skin_tone_undertone,
    gender: scanData.gender,
    body_size_estimate: scanData.size_estimate,
    height_cm: scanData.height_cm,
  }) || null;
  const profileTags = profile ? [
    profile.body_shape && profile.body_shape !== 'unknown' && { label: 'Body shape', value: mapBodyShape(profile.body_shape) },
    profile.skin_tone_undertone && { label: 'Undertone', value: mapUndertone(profile.skin_tone_undertone) },
    profile.skin_tone_category && { label: 'Depth', value: mapSkinDepth(profile.skin_tone_category) },
    profile.body_size_estimate && profile.body_size_estimate !== 'unknown' && { label: 'Size', value: profile.body_size_estimate },
    // The estimator can return nonsense on a cropped/partial frame (saw
    // 56 cm live) -- don't put an impossible number on the mirror.
    profile.height_cm >= 120 && profile.height_cm <= 220 && { label: 'Height', value: `${Math.round(profile.height_cm)} cm` },
  ].filter(Boolean) : [];

  // Department (men's / women's) confirm-or-correct control. The gender
  // ensemble is ~95% right, but a mirror must never be stuck on the wrong
  // department, so the customer can flip it with one tap. Saved to the scan
  // row so Aria and every later call agree; scanData is updated locally so
  // the fetch effect re-runs immediately.
  const [savingGender, setSavingGender] = useState(false);
  const detectedGender = profile?.gender || 'unknown';
  const chooseGender = async (gender) => {
    if (!sessionId || savingGender || gender === detectedGender) return;
    markInteraction();
    setSavingGender(true);
    try {
      await apiPostJSON('/api/vision/scan/gender', { session_id: sessionId, gender });
      setScanProfile((prev) => (prev ? { ...prev, gender } : prev));
      setScanData((prev) => (prev ? { ...prev, gender } : prev));
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingGender(false);
    }
  };


  return (
    <div className="recommendations-page">
      <motion.div
        className="rec-page-header"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="rec-page-title">
          <div className="rec-title-icon">
            <RiSparklingLine />
          </div>
          <div>
            <h1>
              AI <span className="gradient-text">Recommendations</span>
            </h1>
            <p>{noScan ? 'Run a body scan first to get personalized picks' : 'Curated picks based on your style DNA'}</p>
          </div>
        </div>
      </motion.div>

      {profile && (
        <motion.div
          className="rec-scan-profile"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
        >
          <span className="rec-scan-profile-label">
            <RiShieldCheckLine /> Based on your scan
          </span>
          {profile?.gender_locked ? (
            <span className="rec-meta-tag">
              <strong>Range:</strong>&nbsp;{detectedGender === 'male' ? "Men's" : "Women's"}
            </span>
          ) : (
          <span className="rec-meta-tag rec-range-control" title="Tap to change which range you see">
            <strong>Range:</strong>
            {['female', 'male'].map((g) => (
              <button
                key={g}
                type="button"
                className={`rec-range-btn${detectedGender === g ? ' active' : ''}`}
                disabled={savingGender}
                onClick={() => chooseGender(g)}
              >
                {g === 'female' ? "Women's" : "Men's"}
              </button>
            ))}
            {detectedGender === 'unknown' && <em>not sure — pick one</em>}
          </span>
          )}
          {profileTags.map((t) => (
            <span key={t.label} className="rec-meta-tag">
              <strong>{t.label}:</strong>&nbsp;{t.value}
            </span>
          ))}
        </motion.div>
      )}

      <motion.div
        className="rec-include"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08 }}
      >
        <span className="rec-include-label">What should I include?</span>
        {INCLUDE_OPTIONS.map((opt) => {
          const on = includeKeys.includes(opt.key);
          return (
            <button
              key={opt.key}
              type="button"
              className={`rec-include-btn${on ? ' active' : ''}`}
              onClick={() => {
                markInteraction();
                setIncludeKeys((prev) => (on ? prev.filter((k) => k !== opt.key) : [...prev, opt.key]));
              }}
            >
              {opt.label}
            </button>
          );
        })}
        {includeKeys.length > 0 && (
          <button
            type="button"
            className="rec-include-btn rec-include-reset"
            onClick={() => { markInteraction(); setIncludeKeys([]); }}
          >
            Show everything
          </button>
        )}
      </motion.div>

      <motion.div
        className="rec-filters"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <FilterChips
          filters={categories}
          activeFilter={activeFilter}
          onSelect={(f) => { markInteraction(); setActiveFilter(f); }}
        />
        {occasions.length > 1 && (
          <FilterChips
            filters={occasions}
            activeFilter={activeOccasion}
            onSelect={(f) => { markInteraction(); setActiveOccasion(f); }}
          />
        )}
      </motion.div>

      {loading && (
        <motion.div
          style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <RiLoader4Line style={{ fontSize: '2rem', animation: 'spin 1s linear infinite' }} />
          <p style={{ marginTop: '0.5rem' }}>Finding your perfect matches...</p>
        </motion.div>
      )}

      {error && (
        <motion.div
          style={{ textAlign: 'center', padding: '2rem', color: 'var(--error, #ef4444)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <RiErrorWarningLine style={{ fontSize: '1.5rem' }} />
          <p style={{ marginTop: '0.5rem' }}>{error}</p>
        </motion.div>
      )}

      {!loading && !error && showSections && (
        <motion.div
          className="rec-sections"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
        >
          {sections.map((sec, si) => (
            <section key={sec.category} className="rec-section">
              <div className="rec-section-header">
                <h2>{sec.label}</h2>
                <span>
                  {Array.isArray(sec.groups) && sec.groups.length > 0
                    ? `${sec.groups.length} type${sec.groups.length === 1 ? '' : 's'} · ${sec.items.length} options`
                    : `${sec.items.length} pick${sec.items.length === 1 ? '' : 's'} for you`}
                </span>
              </div>
              {Array.isArray(sec.groups) && sec.groups.length > 0 ? (
                // Styled look: one row per garment TYPE ("Heels & Wedges",
                // "Kurtas & Kurtis", "Formal") with its 2-3 options.
                sec.groups.map((group, gi) => (
                  <div key={group.label} className="rec-group">
                    <div className="rec-group-header">
                      <h3>{group.label}</h3>
                      <span>{group.items.length} option{group.items.length === 1 ? '' : 's'}</span>
                    </div>
                    <div className="rec-product-grid">
                      {group.items.map((product, index) => renderCard(product, (si * 10 + gi) * 3 + index))}
                    </div>
                  </div>
                ))
              ) : (
                <div className="rec-product-grid">
                  {sec.items.map((product, index) => renderCard(product, si * 3 + index))}
                </div>
              )}
            </section>
          ))}
        </motion.div>
      )}

      {!loading && !error && !showSections && (
        <AnimatePresence mode="wait">
          <motion.div
            key={activeFilter}
            className="rec-product-grid"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            {products.length === 0 && !noScan && (
              <p style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--text-secondary)', padding: '2rem' }}>
                No recommendations yet. Make sure inventory has been seeded.
              </p>
            )}
            {products.map((product, index) => renderCard(product, index))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
