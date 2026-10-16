import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiSearchLine,
  RiShoppingCartLine,
  RiHeartLine,
  RiHeartFill,
  RiStoreLine,
  RiAddLine,
  RiSubtractLine,
  RiDeleteBinLine,
  RiCloseLine,
  RiShoppingBag3Line,
  RiArrowRightLine,
  RiPriceTag3Line,
  RiTruckLine,
  RiShieldCheckLine,
  RiFilterLine,
  RiLoader4Line,
  RiCalendarEventLine,
  RiArchiveLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import FilterChips from '../components/Common/FilterChips';
import { apiGetJSON, apiPostJSON } from '../utils/api';
import { useSession } from '../context/SessionContext';
import { logEventNow, useImpressionLogger } from '../hooks/useEventLogger';
import { useAriaAction } from '../utils/ariaBus';
import './Shopping.css';

const EMOJI_BY_CATEGORY = {
  top: '👕', bottom: '👖', dress: '👗', footwear: '👟',
  bag: '👜', jewelry: '💍', watch: '⌚', accessory: '🧣',
};

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
};

const cardVariants = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.9, transition: { duration: 0.2 } },
};

/** Extracted so useImpressionLogger can attach its own IntersectionObserver
 * per card -- hooks can't be called inside a .map() body in the parent. */
const ProductCard = ({ product, sessionId, wishlisted, highlighted, owned, onWishlist, onAddToCart, onReserve, onOwn, formatPrice, emoji }) => {
  const cardRef = useRef(null);
  useImpressionLogger(sessionId, product.id, cardRef);
  return (
    <motion.div
      ref={cardRef}
      className={`product-card${highlighted ? ' product-card-highlighted' : ''}`}
      data-item-id={product.id}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      layout
      whileHover={{ y: -4 }}
    >
      <div className="product-image">
        {product.image_url ? (
          <img src={product.image_url} alt={product.name} className="product-img" />
        ) : (
          <div className="image-placeholder">
            <span className="placeholder-emoji">{emoji}</span>
          </div>
        )}
        {product.stock <= 3 && product.stock > 0 && (
          <span className="product-badge badge-sale">
            <RiPriceTag3Line /> Only {product.stock} left
          </span>
        )}
        <button
          className={`wishlist-btn ${wishlisted ? 'wishlisted' : ''}`}
          onClick={() => onWishlist(product.id)}
          aria-label="Toggle wishlist"
        >
          {wishlisted ? <RiHeartFill /> : <RiHeartLine />}
        </button>
      </div>

      <div className="product-info">
        <span className="product-brand">{product.category}</span>
        <h3 className="product-name">{product.name}</h3>
        {product.color && <span className="product-color-tag">{product.color}</span>}
        <div className="product-price">
          <span className="current-price">{formatPrice(product.price)}</span>
          {product.stock > 0 && <span className="stock-info">In stock</span>}
        </div>
      </div>

      <div className="product-actions">
        <button className="action-btn reserve-btn" onClick={() => onReserve(product)}>
          <RiStoreLine /> Reserve
        </button>
        <button className="action-btn cart-btn" onClick={() => onAddToCart(product)}>
          <RiShoppingCartLine /> Add to Cart
        </button>
      </div>
      {/* Wardrobe: "I already own this" -- future looks are built around it. */}
      <button
        className={`action-btn own-btn${owned ? ' owned' : ''}`}
        onClick={() => onOwn(product)}
        title={owned ? 'In your wardrobe' : 'Save as something you already own'}
      >
        <RiArchiveLine /> {owned ? 'In your wardrobe' : 'I own this'}
      </button>
    </motion.div>
  );
};

const Shopping = () => {
  const {
    sessionId, fireAgentEvent, cart, addToCart: addToSharedCart, removeFromCart, setCartQuantity,
    cartOpen, setCartOpen, liked, likeItem, unlikeItem, registerItems, setScreenItems,
    highlightedItemId, setHighlightedItemId,
  } = useSession();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('All');
  const [occasions, setOccasions] = useState([]);
  const [activeOccasion, setActiveOccasion] = useState('All');
  // Cart, liked list and cart drawer are shared app-wide (SessionContext),
  // so voice actions and the Recommendations hearts see the same state.
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [limit, setLimit] = useState(48);
  // Ids the customer has marked "I already own this" (wardrobe).
  const [ownedIds, setOwnedIds] = useState(() => new Set());

  const loadProducts = useCallback(async () => {
    setLoading(true);
    try {
      const catParam = activeFilter !== 'All' ? `&category=${encodeURIComponent(activeFilter)}` : '';
      const occasionParam = activeOccasion !== 'All' ? `&occasion=${encodeURIComponent(activeOccasion)}` : '';
      const searchParam = searchQuery.trim() ? `&search=${encodeURIComponent(searchQuery)}` : '';
      const data = await apiGetJSON(`/api/inventory/browse?limit=${limit}${catParam}${occasionParam}${searchParam}`);
      setProducts(data.items || []);
    } catch (err) {
      console.error('Failed to load inventory:', err);
    } finally {
      setLoading(false);
    }
  }, [activeFilter, activeOccasion, searchQuery, limit]);

  useEffect(() => {
    const timer = setTimeout(loadProducts, searchQuery ? 300 : 0);
    return () => clearTimeout(timer);
  }, [loadProducts, searchQuery]);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGetJSON('/api/inventory/categories');
        setCategories(['All', ...(data.categories || [])]);
      } catch {
        setCategories(['All']);
      }
    })();
    (async () => {
      try {
        const data = await apiGetJSON('/api/inventory/occasions');
        setOccasions(['All', ...(data.occasions || [])]);
      } catch {
        setOccasions(['All']);
      }
    })();
  }, []);

  // Wardrobe items already saved this session -- so the button renders in the
  // right state when she comes back to this page.
  useEffect(() => {
    if (!sessionId) return;
    (async () => {
      try {
        const data = await apiGetJSON(`/api/wardrobe/${sessionId}`);
        setOwnedIds(new Set((data.items || []).map((i) => String(i.id))));
      } catch { /* wardrobe is optional -- the page works without it */ }
    })();
  }, [sessionId]);

  const filterOptions = useMemo(() => categories, [categories]);
  const occasionOptions = useMemo(() => occasions, [occasions]);

  const addToCart = (product) => {
    addToSharedCart(product);
    setCartOpen(true);
    logEventNow(sessionId, product.id, 'add_to_cart', { source: 'shopping', category: product.category });
    // Proactive engagement: let Aria notice and suggest a matching item.
    // Only on first-time adds (not quantity bumps) so we don't spam.
    if (fireAgentEvent && !cart.find((item) => String(item.id) === String(product.id))) {
      fireAgentEvent('cart_item_added');
    }
  };

  const updateCartQuantity = (productId, delta) => setCartQuantity(productId, { delta });

  // Wardrobe ("I own this") -- the backend stores it against the session, so
  // "what goes with my wardrobe" can build looks around these pieces.
  const toggleOwned = async (product) => {
    const id = String(product.id);
    const isOwned = ownedIds.has(id);
    setOwnedIds((prev) => {
      const next = new Set(prev);
      if (isOwned) next.delete(id); else next.add(id);
      return next;
    });
    try {
      await apiPostJSON(`/api/wardrobe/${isOwned ? 'remove' : 'add'}`,
        { session_id: sessionId, item_id: id });
    } catch (err) {
      console.warn('[wardrobe] save failed', err);
      setOwnedIds((prev) => {               // roll back on failure
        const next = new Set(prev);
        if (isOwned) next.add(id); else next.delete(id);
        return next;
      });
    }
  };

  const toggleWishlist = (productId) => {
    const wasWishlisted = !!liked[String(productId)];
    if (wasWishlisted) unlikeItem(productId);
    else likeItem(products.find((p) => String(p.id) === String(productId)) || productId);
    logEventNow(sessionId, productId, wasWishlisted ? 'dismiss' : 'click', {
      source: 'shopping', action: 'wishlist_toggle',
    });
  };

  // Favourites view ("show my favourites") shows the shared liked list.
  const shownProducts = useMemo(
    () => (favouritesOnly ? Object.values(liked) : products),
    [favouritesOnly, liked, products],
  );

  useEffect(() => {
    registerItems(products);
  }, [products, registerItems]);

  useEffect(() => {
    setScreenItems(shownProducts.map((p) => ({
      id: String(p.id), name: p.name, color: p.color,
      category: p.category, image_url: p.image_url,
    })));
  }, [shownProducts, setScreenItems]);

  // Voice control (docs/dataset/new_actions.json).
  const matchChip = (options, value) => {
    if (!value || value === 'all') return 'All';
    return options.find((o) => o.toLowerCase() === String(value).toLowerCase()) || 'All';
  };
  useAriaAction(
    ['set_category_filter', 'set_occasion_filter', 'clear_filters', 'search', 'clear_search',
      'show_liked', 'focus_item', 'load_more', 'paginate'],
    (payload, type) => {
      switch (type) {
        case 'set_category_filter':
          setFavouritesOnly(false);
          setActiveFilter(matchChip(categories, payload.category));
          break;
        case 'set_occasion_filter':
          setFavouritesOnly(false);
          setActiveOccasion(matchChip(occasions, payload.occasion));
          break;
        case 'clear_filters':
          setFavouritesOnly(false);
          if (!payload.scope || payload.scope === 'all' || payload.scope === 'category') setActiveFilter('All');
          if (!payload.scope || payload.scope === 'all' || payload.scope === 'occasion') setActiveOccasion('All');
          if (!payload.scope || payload.scope === 'all') setSearchQuery('');
          break;
        case 'search':
          setFavouritesOnly(false);
          setSearchQuery((q) => (payload.refine && q ? `${q} ${payload.query}` : payload.query || ''));
          break;
        case 'clear_search':
          setSearchQuery('');
          break;
        case 'show_liked':
          setFavouritesOnly(true);
          break;
        case 'load_more':
        case 'paginate':
          if (type === 'load_more' || payload.direction !== 'previous') setLimit((l) => l + (payload.count || 24));
          break;
        case 'focus_item':
          setHighlightedItemId(payload.item_id || null);
          setTimeout(() => {
            document.querySelector(`[data-item-id="${payload.item_id}"]`)
              ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }, 150);
          break;
        default:
          break;
      }
    },
  );

  const cartTotal = cart.reduce((sum, item) => sum + (item.price || 0) * item.quantity, 0);
  const cartItemCount = cart.reduce((sum, item) => sum + item.quantity, 0);

  const formatPrice = (price) => {
    if (!price) return 'Price N/A';
    return price >= 1000 ? `₹${price.toLocaleString()}` : `₹${price}`;
  };

  return (
    <motion.div
      className="shopping-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div className="shopping-header" variants={itemVariants}>
        <div className="header-content">
          <h1 className="page-title">
            <RiShoppingBag3Line className="title-icon" />
            Shopping
          </h1>
          <p className="page-subtitle">
            Browse our real in-store inventory
          </p>
        </div>
        <motion.button
          className="cart-toggle"
          onClick={() => setCartOpen(!cartOpen)}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
        >
          <RiShoppingCartLine />
          {cartItemCount > 0 && (
            <motion.span
              className="cart-badge"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              key={cartItemCount}
            >
              {cartItemCount}
            </motion.span>
          )}
        </motion.button>
      </motion.div>

      <motion.div className="shopping-controls" variants={itemVariants}>
        <div className="search-bar">
          <RiSearchLine className="search-icon" />
          <input
            type="text"
            placeholder="Search products, colors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button className="search-clear" onClick={() => setSearchQuery('')}>
              <RiCloseLine />
            </button>
          )}
        </div>
        {favouritesOnly && (
          <div className="filter-row">
            <RiHeartFill className="filter-icon" />
            <FilterChips
              filters={['Favourites', 'Show all']}
              activeFilter="Favourites"
              onSelect={(f) => setFavouritesOnly(f === 'Favourites')}
            />
          </div>
        )}
        <div className="filter-row">
          <RiFilterLine className="filter-icon" />
          <FilterChips
            filters={filterOptions}
            activeFilter={activeFilter}
            onSelect={setActiveFilter}
          />
        </div>
        {occasionOptions.length > 1 && (
          <div className="filter-row">
            <RiCalendarEventLine className="filter-icon" />
            <FilterChips
              filters={occasionOptions}
              activeFilter={activeOccasion}
              onSelect={setActiveOccasion}
            />
          </div>
        )}
      </motion.div>

      <div className={`shopping-content ${cartOpen ? 'cart-visible' : ''}`}>
        <div className="product-grid">
          {loading ? (
            <motion.div className="no-results" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <RiLoader4Line className="no-results-icon spinning" />
              <h3>Loading inventory...</h3>
            </motion.div>
          ) : (
            <AnimatePresence mode="popLayout">
              {shownProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  sessionId={sessionId}
                  wishlisted={!!liked[String(product.id)]}
                  highlighted={String(product.id) === String(highlightedItemId)}
                  owned={ownedIds.has(String(product.id))}
                  onWishlist={toggleWishlist}
                  onOwn={toggleOwned}
                  onAddToCart={addToCart}
                  onReserve={(p) => logEventNow(sessionId, p.id, 'click', { source: 'shopping', action: 'reserve' })}
                  formatPrice={formatPrice}
                  emoji={EMOJI_BY_CATEGORY[product.category] || '👔'}
                />
              ))}
            </AnimatePresence>
          )}

          {!loading && shownProducts.length === 0 && (
            <motion.div className="no-results" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <RiSearchLine className="no-results-icon" />
              <h3>{favouritesOnly ? 'No favourites yet' : 'No products found'}</h3>
              <p>{favouritesOnly ? 'Say "like this one" when something catches your eye' : 'Try adjusting your search or filters'}</p>
            </motion.div>
          )}
        </div>

        <AnimatePresence>
          {cartOpen && (
            <motion.div
              className="cart-sidebar"
              initial={{ x: 300, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 300, opacity: 0 }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            >
              <GlassCard>
                <div className="cart-header">
                  <h2><RiShoppingCartLine /> Your Cart</h2>
                  <button className="cart-close" onClick={() => setCartOpen(false)}>
                    <RiCloseLine />
                  </button>
                </div>

                {cart.length === 0 ? (
                  <div className="cart-empty">
                    <RiShoppingBag3Line className="cart-empty-icon" />
                    <p>Your cart is empty</p>
                    <span>Add some items to get started</span>
                  </div>
                ) : (
                  <>
                    <div className="cart-items">
                      <AnimatePresence>
                        {cart.map((item) => (
                          <motion.div
                            key={item.id}
                            className="cart-item"
                            initial={{ opacity: 0, x: 50 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: -50, height: 0, marginBottom: 0 }}
                            transition={{ duration: 0.3 }}
                            layout
                          >
                            <div className="cart-item-image">
                              <span>{EMOJI_BY_CATEGORY[item.category] || '👔'}</span>
                            </div>
                            <div className="cart-item-details">
                              <span className="cart-item-name">{item.name}</span>
                              <span className="cart-item-brand">{item.category}</span>
                              <span className="cart-item-price">
                                {formatPrice((item.price || 0) * item.quantity)}
                              </span>
                            </div>
                            <div className="cart-item-controls">
                              <button className="qty-btn" onClick={() => updateCartQuantity(item.id, -1)}>
                                <RiSubtractLine />
                              </button>
                              <span className="qty-value">{item.quantity}</span>
                              <button className="qty-btn" onClick={() => updateCartQuantity(item.id, 1)}>
                                <RiAddLine />
                              </button>
                              <button className="remove-btn" onClick={() => removeFromCart(item.id)}>
                                <RiDeleteBinLine />
                              </button>
                            </div>
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </div>

                    <div className="cart-summary">
                      <div className="cart-summary-row">
                        <span>Items</span>
                        <span>{cartItemCount}</span>
                      </div>
                      <div className="cart-summary-total">
                        <span>Total</span>
                        <span>{formatPrice(cartTotal)}</span>
                      </div>
                      <AnimatedButton className="checkout-btn">
                        <RiArrowRightLine /> Checkout
                      </AnimatedButton>
                      <div className="cart-trust-badges">
                        <span><RiTruckLine /> Free Returns</span>
                        <span><RiShieldCheckLine /> Secure Checkout</span>
                      </div>
                    </div>
                  </>
                )}
              </GlassCard>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
};

export default Shopping;
