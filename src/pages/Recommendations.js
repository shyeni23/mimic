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
import { apiPostJSON } from '../utils/api';
import './Recommendations.css';

const categories = ['All', 'Tops', 'Bottoms', 'Shoes', 'Bags', 'Accessories'];

const EMOJI_BY_CATEGORY = {
  tops: '👕', bottoms: '👖', shoes: '👟', bags: '👜',
  accessories: '💍', watches: '⌚', jewelry: '💎',
};
const GRADIENT_BY_CATEGORY = {
  tops: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
  bottoms: 'linear-gradient(135deg, #434343 0%, #000000 100%)',
  shoes: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
  bags: 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)',
  accessories: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
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

export default function Recommendations() {
  const {
    sessionId, scanData,
    pendingRecommendations, setPendingRecommendations,
    highlightedItemId, setHighlightedItemId,
    fireAgentEvent,
  } = useSession();
  const [activeFilter, setActiveFilter] = useState('All');
  const [favorites, setFavorites] = useState({});
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchRecommendations = useCallback(async (category) => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const body = { session_id: sessionId };
      if (category && category !== 'All') {
        body.category = category.toLowerCase();
      }
      const data = await apiPostJSON('/api/recommend', body);
      setProducts((data.results || []).map(normalizeProduct));
    } catch (err) {
      setError(err.message);
      setProducts([]);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Phase B (Module 2): if the chat agent already fetched results via its
  // recommend_clothes tool and queued a show_recommendations action, use
  // those directly instead of re-fetching -- avoids a redundant API call and
  // shows exactly what Aria referenced in her reply.
  useEffect(() => {
    if (pendingRecommendations) {
      setProducts(pendingRecommendations.map(normalizeProduct));
      setPendingRecommendations(null);
    }
  }, [pendingRecommendations, setPendingRecommendations]);

  useEffect(() => {
    if (sessionId && scanData && !pendingRecommendations) {
      fetchRecommendations(activeFilter);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, scanData, activeFilter, fetchRecommendations]);

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

  const toggleFavorite = (id) => {
    markInteraction();
    setFavorites((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const noScan = !scanData;

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

      {!loading && !error && (
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
            {products.map((product, index) => (
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
                    onClick={() => toggleFavorite(product.id)}
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
                    onClick={markInteraction}
                  >
                    Add to Outfit
                  </AnimatedButton>
                </div>
              </GlassCard>
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
