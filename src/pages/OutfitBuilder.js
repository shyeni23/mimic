import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence, LayoutGroup } from 'framer-motion';
import {
  RiShirtLine,
  RiFootprintLine,
  RiHandbagLine,
  RiTimeLine,
  RiSparklingLine,
  RiSaveLine,
  RiShareLine,
  RiCloseLine,
  RiAddLine,
  RiTShirtLine,
  RiLoader4Line,
  RiErrorWarningLine,
  RiMagicLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import { useSession } from '../context/SessionContext';
import AnimatedButton from '../components/Common/AnimatedButton';
import { apiGetJSON } from '../utils/api';
import './OutfitBuilder.css';

// Maps the backend's inventory categories (top/bottom/dress/footwear/bag/
// jewelry/watch/accessory -- see backend/app/db/schema.sql) onto this page's
// existing mannequin slot ids. "dress" has no dedicated slot here, so it's
// shown in the "top" slot -- it's the outfit's centerpiece either way.
// jewelry and accessory both land on "accessories"; applyAiOutfit() below
// never overwrites an already-filled slot, and the backend returns jewelry
// before accessory (see outfit_recommendation.py's OUTFIT_SLOTS), so jewelry
// wins when a recommendation includes both.
const BACKEND_CATEGORY_TO_SLOT = {
  top: 'top',
  bottom: 'bottom',
  dress: 'top',
  footwear: 'shoes',
  bag: 'bag',
  watch: 'watch',
  jewelry: 'accessories',
  accessory: 'accessories',
};

const AI_ITEM_EMOJI = {
  top: '👕', bottom: '👖', dress: '👗', footwear: '👟',
  bag: '👜', watch: '⌚', jewelry: '💎', accessory: '🕶️',
};

function toBuilderItem(row, category) {
  return {
    id: row.id,
    name: row.name,
    brand: row.color ? row.color[0].toUpperCase() + row.color.slice(1) : '',
    emoji: AI_ITEM_EMOJI[category] || '✨',
    color: row.color || '#6C63FF',
    image_url: row.image_url || null,
    explanation: row.explanation,
    score: row.score,
    aiPicked: true,
  };
}

const CATEGORIES = [
  { id: 'top', label: 'Top', icon: <RiTShirtLine /> },
  { id: 'bottom', label: 'Bottom', icon: <RiShirtLine /> },
  { id: 'shoes', label: 'Shoes', icon: <RiFootprintLine /> },
  { id: 'bag', label: 'Bag', icon: <RiHandbagLine /> },
  { id: 'watch', label: 'Watch', icon: <RiTimeLine /> },
  { id: 'accessories', label: 'Accessories', icon: <RiSparklingLine /> },
];

const ITEMS_DATA = {
  top: [
    { id: 't1', name: 'Classic Tee', brand: 'Zara', emoji: '👕', color: '#6C63FF' },
    { id: 't2', name: 'Silk Blouse', brand: 'H&M', emoji: '👔', color: '#00C2FF' },
    { id: 't3', name: 'Crop Hoodie', brand: 'Nike', emoji: '🧥', color: '#8B5CF6' },
    { id: 't4', name: 'Linen Shirt', brand: 'Uniqlo', emoji: '👕', color: '#10B981' },
    { id: 't5', name: 'Knit Sweater', brand: 'COS', emoji: '🧶', color: '#F59E0B' },
    { id: 't6', name: 'Denim Jacket', brand: 'Levi\'s', emoji: '🧥', color: '#3B82F6' },
  ],
  bottom: [
    { id: 'b1', name: 'Slim Jeans', brand: 'Levi\'s', emoji: '👖', color: '#3B82F6' },
    { id: 'b2', name: 'Pleated Skirt', brand: 'Zara', emoji: '🩳', color: '#EC4899' },
    { id: 'b3', name: 'Cargo Pants', brand: 'H&M', emoji: '👖', color: '#6B7280' },
    { id: 'b4', name: 'Wide Leg Trousers', brand: 'COS', emoji: '👖', color: '#1F2937' },
    { id: 'b5', name: 'Mini Skirt', brand: 'ASOS', emoji: '🩳', color: '#F472B6' },
    { id: 'b6', name: 'Joggers', brand: 'Nike', emoji: '👖', color: '#4B5563' },
  ],
  shoes: [
    { id: 's1', name: 'White Sneakers', brand: 'Nike', emoji: '👟', color: '#F9FAFB' },
    { id: 's2', name: 'Ankle Boots', brand: 'Dr. Martens', emoji: '👢', color: '#1F2937' },
    { id: 's3', name: 'Heeled Sandals', brand: 'Steve Madden', emoji: '👡', color: '#D97706' },
    { id: 's4', name: 'Loafers', brand: 'Gucci', emoji: '👞', color: '#78350F' },
    { id: 's5', name: 'Running Shoes', brand: 'Adidas', emoji: '👟', color: '#6C63FF' },
    { id: 's6', name: 'Platform Boots', brand: 'Zara', emoji: '👢', color: '#111827' },
  ],
  bag: [
    { id: 'bg1', name: 'Tote Bag', brand: 'Coach', emoji: '👜', color: '#92400E' },
    { id: 'bg2', name: 'Crossbody', brand: 'Kate Spade', emoji: '👝', color: '#EC4899' },
    { id: 'bg3', name: 'Backpack', brand: 'Herschel', emoji: '🎒', color: '#1F2937' },
    { id: 'bg4', name: 'Clutch', brand: 'YSL', emoji: '👛', color: '#6C63FF' },
    { id: 'bg5', name: 'Bucket Bag', brand: 'Mansur Gavriel', emoji: '👜', color: '#D97706' },
    { id: 'bg6', name: 'Belt Bag', brand: 'Fendi', emoji: '👝', color: '#8B5CF6' },
  ],
  watch: [
    { id: 'w1', name: 'Classic Gold', brand: 'Casio', emoji: '⌚', color: '#D97706' },
    { id: 'w2', name: 'Smart Watch', brand: 'Apple', emoji: '⌚', color: '#6B7280' },
    { id: 'w3', name: 'Diver Watch', brand: 'Seiko', emoji: '⌚', color: '#1E40AF' },
    { id: 'w4', name: 'Minimalist', brand: 'Daniel Wellington', emoji: '⌚', color: '#F9FAFB' },
    { id: 'w5', name: 'Chronograph', brand: 'Fossil', emoji: '⌚', color: '#374151' },
    { id: 'w6', name: 'Vintage Leather', brand: 'Timex', emoji: '⌚', color: '#92400E' },
  ],
  accessories: [
    { id: 'a1', name: 'Gold Necklace', brand: 'Mejuri', emoji: '📿', color: '#D97706' },
    { id: 'a2', name: 'Silk Scarf', brand: 'Hermes', emoji: '🧣', color: '#EC4899' },
    { id: 'a3', name: 'Sunglasses', brand: 'Ray-Ban', emoji: '🕶️', color: '#1F2937' },
    { id: 'a4', name: 'Baseball Cap', brand: 'New Era', emoji: '🧢', color: '#1E40AF' },
    { id: 'a5', name: 'Leather Belt', brand: 'Gucci', emoji: '🪢', color: '#78350F' },
    { id: 'a6', name: 'Hoop Earrings', brand: 'Pandora', emoji: '💎', color: '#C084FC' },
  ],
};

const MANNEQUIN_SLOTS = ['top', 'bottom', 'shoes', 'bag', 'watch', 'accessories'];

const SLOT_TO_INV_CATEGORY = {
  top: 'top', bottom: 'bottom', shoes: 'footwear',
  bag: 'bag', watch: 'watch', accessories: 'accessory',
};

const SLOT_EMOJI = {
  top: '👕', bottom: '👖', shoes: '👟',
  bag: '👜', watch: '⌚', accessories: '🕶️',
};

export default function OutfitBuilder() {
  const { sessionId, scanData, consumeOutfitActions } = useSession();
  const [selectedCategory, setSelectedCategory] = useState('top');
  const [selectedItems, setSelectedItems] = useState({});
  const [paletteItems, setPaletteItems] = useState(ITEMS_DATA);
  const [outfitName, setOutfitName] = useState('');
  const [saveAnimation, setSaveAnimation] = useState(false);

  // Module 3: the real AI-generated complete outfit from
  // GET /api/outfit-recommendation/{session_id} (backend/app/services/fashion/
  // outfit_recommendation.py) -- overallScore/error track that call
  // specifically, separate from the manual picker above.
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const [aiOverallScore, setAiOverallScore] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function loadPalette() {
      try {
        const data = await apiGetJSON('/api/inventory/browse?limit=200');
        if (cancelled || !data.items?.length) return;
        const grouped = {};
        for (const slot of MANNEQUIN_SLOTS) {
          const invCat = SLOT_TO_INV_CATEGORY[slot];
          const items = data.items
            .filter(i => i.category === invCat)
            .slice(0, 6)
            .map(i => ({
              id: String(i.id),
              name: i.name,
              brand: i.color ? i.color[0].toUpperCase() + i.color.slice(1) : '',
              emoji: SLOT_EMOJI[slot] || '✨',
              color: '#6C63FF',
              image_url: i.image_url || null,
            }));
          grouped[slot] = items.length ? items : ITEMS_DATA[slot];
        }
        setPaletteItems(grouped);
      } catch {
        // keep ITEMS_DATA fallback
      }
    }
    loadPalette();
    return () => { cancelled = true; };
  }, []);

  const handleAddItem = useCallback((category, item) => {
    setSelectedItems((prev) => ({
      ...prev,
      [category]: item,
    }));
  }, []);

  const handleRemoveItem = useCallback((category) => {
    setSelectedItems((prev) => {
      const updated = { ...prev };
      delete updated[category];
      return updated;
    });
  }, []);

  const handleSaveOutfit = useCallback(() => {
    setSaveAnimation(true);
    setTimeout(() => setSaveAnimation(false), 1500);
  }, []);

  const fetchAiOutfit = useCallback(async () => {
    if (!sessionId) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const data = await apiGetJSON(`/api/outfit-recommendation/${sessionId}`);
      const filled = {};
      const primarySlot = BACKEND_CATEGORY_TO_SLOT[data.primary_item.category] || 'top';
      filled[primarySlot] = toBuilderItem(
        { ...data.primary_item, explanation: 'Your AI-picked centerpiece for this look' },
        data.primary_item.category,
      );
      for (const outfitSlot of data.slots || []) {
        const slotId = BACKEND_CATEGORY_TO_SLOT[outfitSlot.slot];
        if (!slotId || filled[slotId]) continue; // never overwrite an already-filled slot
        filled[slotId] = toBuilderItem(
          { ...outfitSlot.item, explanation: outfitSlot.explanation, score: outfitSlot.score },
          outfitSlot.slot,
        );
      }
      setSelectedItems(filled);
      setAiOverallScore(data.overall_score);
    } catch (err) {
      setAiError(err.message);
    } finally {
      setAiLoading(false);
    }
  }, [sessionId]);

  // Auto-load the AI outfit as soon as a fresh scan is available -- mirrors
  // Recommendations.js's pattern for Module 1.
  useEffect(() => {
    if (sessionId && scanData) {
      fetchAiOutfit();
    }
  }, [sessionId, scanData, fetchAiOutfit]);

  useEffect(() => {
    const actions = consumeOutfitActions();
    for (const action of actions) {
      switch (action.type) {
        case 'select_outfit_category':
          setSelectedCategory(action.payload?.category || 'top');
          break;
        case 'set_outfit_item': {
          const cat = action.payload?.category;
          const desc = (action.payload?.item_description || '').toLowerCase();
          const item = paletteItems[cat]?.find((i) =>
            i.name.toLowerCase().includes(desc)
          );
          if (item) handleAddItem(cat, item);
          break;
        }
        case 'remove_outfit_item':
          handleRemoveItem(action.payload?.category);
          break;
        case 'set_outfit_name':
          setOutfitName(action.payload?.name || '');
          break;
        case 'save_outfit':
          handleSaveOutfit();
          break;
        default:
          break;
      }
    }
  }, [consumeOutfitActions, handleAddItem, handleRemoveItem, handleSaveOutfit, paletteItems]);

  const totalSlots = MANNEQUIN_SLOTS.length;
  const filledSlots = Object.keys(selectedItems).length;
  const completionPercent = Math.round((filledSlots / totalSlots) * 100);

  return (
    <motion.div
      className="outfit-builder-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="outfit-builder-header">
        <motion.h1
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          Outfit Builder
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          {!scanData
            ? 'Run a body scan first to get an AI-recommended outfit'
            : 'Mix and match pieces, or let Aria build the whole look for you'}
        </motion.p>
      </div>

      {aiLoading && (
        <motion.div
          style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-secondary)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <RiLoader4Line style={{ fontSize: '1.5rem', animation: 'spin 1s linear infinite' }} />
          <p style={{ marginTop: '0.5rem' }}>Building your AI-recommended outfit...</p>
        </motion.div>
      )}

      {aiError && (
        <motion.div
          style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--error, #ef4444)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <RiErrorWarningLine style={{ fontSize: '1.5rem' }} />
          <p style={{ marginTop: '0.5rem' }}>Couldn't load an AI outfit: {aiError}</p>
        </motion.div>
      )}

      <div className="outfit-builder-content">
        {/* Left Panel - Category & Items */}
        <GlassCard className="outfit-panel items-panel" hover={false}>
          <div className="category-tabs">
            {CATEGORIES.map((cat) => (
              <motion.button
                key={cat.id}
                className={`category-pill ${selectedCategory === cat.id ? 'active' : ''}`}
                onClick={() => setSelectedCategory(cat.id)}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                layout
              >
                <span className="pill-icon">{cat.icon}</span>
                <span className="pill-label">{cat.label}</span>
                {selectedItems[cat.id] && <span className="pill-dot" />}
              </motion.button>
            ))}
          </div>

          <div className="items-grid-container">
            <AnimatePresence mode="wait">
              <motion.div
                key={selectedCategory}
                className="items-grid"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{ duration: 0.3 }}
              >
                {(paletteItems[selectedCategory] || []).map((item, index) => {
                  const isSelected = selectedItems[selectedCategory]?.id === item.id;
                  return (
                    <motion.div
                      key={item.id}
                      className={`item-card ${isSelected ? 'selected' : ''}`}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.3, delay: index * 0.05 }}
                      whileHover={{ scale: 1.05, y: -4 }}
                      whileTap={{ scale: 0.95 }}
                      onClick={() => handleAddItem(selectedCategory, item)}
                    >
                      <div
                        className="item-emoji"
                        style={{ '--item-color': item.color }}
                      >
                        {item.image_url ? (
                          <img src={item.image_url} alt={item.name} className="item-emoji-img" />
                        ) : (
                          item.emoji
                        )}
                      </div>
                      <div className="item-info">
                        <span className="item-name">{item.name}</span>
                        <span className="item-brand">{item.brand}</span>
                      </div>
                      {isSelected && (
                        <motion.div
                          className="item-check"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ type: 'spring', stiffness: 500 }}
                        >
                          ✓
                        </motion.div>
                      )}
                    </motion.div>
                  );
                })}
              </motion.div>
            </AnimatePresence>
          </div>
        </GlassCard>

        {/* Center - Outfit Preview / Mannequin */}
        <GlassCard className="outfit-panel preview-panel" hover={false}>
          <h3 className="preview-title">Outfit Preview</h3>
          <LayoutGroup>
            <div className="mannequin-area">
              {MANNEQUIN_SLOTS.map((slotCategory) => {
                const item = selectedItems[slotCategory];
                const categoryInfo = CATEGORIES.find((c) => c.id === slotCategory);
                return (
                  <motion.div
                    key={slotCategory}
                    className={`mannequin-slot ${item ? 'filled' : 'empty'}`}
                    layout
                    transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                  >
                    <AnimatePresence mode="wait">
                      {item ? (
                        <motion.div
                          key={item.id}
                          className="slot-item"
                          initial={{ opacity: 0, scale: 0.5, rotateY: 90 }}
                          animate={{ opacity: 1, scale: 1, rotateY: 0 }}
                          exit={{ opacity: 0, scale: 0.5, rotateY: -90 }}
                          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                          title={item.explanation || undefined}
                        >
                          <span className="slot-emoji">
                            {item.image_url ? (
                              <img src={item.image_url} alt={item.name} className="slot-emoji-img" />
                            ) : (
                              item.emoji
                            )}
                          </span>
                          <div className="slot-details">
                            <span className="slot-name">
                              {item.aiPicked && <RiSparklingLine title="AI pick" />} {item.name}
                            </span>
                            <span className="slot-brand">{item.brand}</span>
                          </div>
                          <motion.button
                            className="slot-remove"
                            onClick={() => handleRemoveItem(slotCategory)}
                            whileHover={{ scale: 1.2, rotate: 90 }}
                            whileTap={{ scale: 0.9 }}
                          >
                            <RiCloseLine />
                          </motion.button>
                        </motion.div>
                      ) : (
                        <motion.div
                          className="slot-placeholder"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                        >
                          <span className="slot-placeholder-icon">
                            {categoryInfo?.icon}
                          </span>
                          <span className="slot-placeholder-label">
                            Add {categoryInfo?.label}
                          </span>
                          <RiAddLine className="slot-add-icon" />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </div>
          </LayoutGroup>
        </GlassCard>

        {/* Right Panel - Summary */}
        <GlassCard className="outfit-panel summary-panel" hover={false}>
          <h3 className="summary-title">Outfit Summary</h3>

          <div className="outfit-name-field">
            <label htmlFor="outfitName">Outfit Name</label>
            <input
              id="outfitName"
              type="text"
              placeholder="My weekend look..."
              value={outfitName}
              onChange={(e) => setOutfitName(e.target.value)}
              className="outfit-name-input"
            />
          </div>

          <div className="summary-stats">
            <div className="stat-row">
              <span className="stat-label">Items Selected</span>
              <span className="stat-value">{filledSlots} / {totalSlots}</span>
            </div>
            <div className="stat-row">
              <span className="stat-label">Completion</span>
              <span className="stat-value">{completionPercent}%</span>
            </div>
            {aiOverallScore !== null && (
              <div className="stat-row">
                <span className="stat-label">AI Match Score</span>
                <span className="stat-value">{Math.round(aiOverallScore * 100)}%</span>
              </div>
            )}
          </div>

          <AnimatedButton
            variant="secondary"
            fullWidth
            icon={<RiMagicLine />}
            onClick={fetchAiOutfit}
            disabled={!sessionId || aiLoading}
          >
            {aiLoading ? 'Building...' : 'Regenerate AI Outfit'}
          </AnimatedButton>

          <div className="completion-bar-container">
            <motion.div
              className="completion-bar-fill"
              initial={{ width: 0 }}
              animate={{ width: `${completionPercent}%` }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
            />
          </div>

          <div className="summary-items-list">
            {MANNEQUIN_SLOTS.map((slotCategory) => {
              const item = selectedItems[slotCategory];
              const categoryInfo = CATEGORIES.find((c) => c.id === slotCategory);
              return (
                <motion.div
                  key={slotCategory}
                  className={`summary-item-row ${item ? 'filled' : ''}`}
                  layout
                >
                  <span className="summary-item-category">
                    {categoryInfo?.icon}
                    <span>{categoryInfo?.label}</span>
                  </span>
                  {item ? (
                    <span className="summary-item-name">
                      {item.emoji} {item.name}
                    </span>
                  ) : (
                    <span className="summary-item-empty">Not selected</span>
                  )}
                </motion.div>
              );
            })}
          </div>

          <div className="summary-actions">
            <AnimatedButton
              variant="primary"
              fullWidth
              icon={<RiSaveLine />}
              onClick={handleSaveOutfit}
              disabled={filledSlots === 0}
              className={saveAnimation ? 'save-success' : ''}
            >
              {saveAnimation ? 'Outfit Saved!' : 'Save Outfit'}
            </AnimatedButton>
            <AnimatedButton
              variant="secondary"
              fullWidth
              icon={<RiShareLine />}
              disabled={filledSlots === 0}
            >
              Share Outfit
            </AnimatedButton>
          </div>
        </GlassCard>
      </div>
    </motion.div>
  );
}
