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
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import FilterChips from '../components/Common/FilterChips';
import { apiGetJSON } from '../utils/api';
import { useSession } from '../context/SessionContext';
import { logEventNow, useImpressionLogger } from '../hooks/useEventLogger';
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
const ProductCard = ({ product, sessionId, wishlisted, onWishlist, onAddToCart, onReserve, formatPrice, emoji }) => {
  const cardRef = useRef(null);
  useImpressionLogger(sessionId, product.id, cardRef);
  return (
    <motion.div
      ref={cardRef}
      className="product-card"
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
    </motion.div>
  );
};

const Shopping = () => {
  const { sessionId, fireAgentEvent } = useSession();
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('All');
  const [occasions, setOccasions] = useState([]);
  const [activeOccasion, setActiveOccasion] = useState('All');
  const [cart, setCart] = useState([]);
  const [wishlist, setWishlist] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);

  const loadProducts = useCallback(async () => {
    setLoading(true);
    try {
      const catParam = activeFilter !== 'All' ? `&category=${encodeURIComponent(activeFilter)}` : '';
      const occasionParam = activeOccasion !== 'All' ? `&occasion=${encodeURIComponent(activeOccasion)}` : '';
      const searchParam = searchQuery.trim() ? `&search=${encodeURIComponent(searchQuery)}` : '';
      const data = await apiGetJSON(`/api/inventory/browse?limit=50${catParam}${occasionParam}${searchParam}`);
      setProducts(data.items || []);
    } catch (err) {
      console.error('Failed to load inventory:', err);
    } finally {
      setLoading(false);
    }
  }, [activeFilter, activeOccasion, searchQuery]);

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

  const filterOptions = useMemo(() => categories, [categories]);
  const occasionOptions = useMemo(() => occasions, [occasions]);

  const addToCart = (product) => {
    setCart((prev) => {
      const existing = prev.find((item) => item.id === product.id);
      if (existing) {
        return prev.map((item) =>
          item.id === product.id ? { ...item, quantity: item.quantity + 1 } : item
        );
      }
      return [...prev, { ...product, quantity: 1 }];
    });
    setCartOpen(true);
    logEventNow(sessionId, product.id, 'add_to_cart', { source: 'shopping', category: product.category });
    // Proactive engagement: let Aria notice and suggest a matching item.
    // Only on first-time adds (not quantity bumps) so we don't spam.
    if (fireAgentEvent && !cart.find((item) => item.id === product.id)) {
      fireAgentEvent('cart_item_added');
    }
  };

  const removeFromCart = (productId) => {
    setCart((prev) => prev.filter((item) => item.id !== productId));
  };

  const updateCartQuantity = (productId, delta) => {
    setCart((prev) =>
      prev
        .map((item) =>
          item.id === productId
            ? { ...item, quantity: Math.max(0, item.quantity + delta) }
            : item
        )
        .filter((item) => item.quantity > 0)
    );
  };

  const toggleWishlist = (productId) => {
    const wasWishlisted = wishlist.includes(productId);
    setWishlist((prev) =>
      wasWishlisted ? prev.filter((id) => id !== productId) : [...prev, productId]
    );
    logEventNow(sessionId, productId, wasWishlisted ? 'dismiss' : 'click', {
      source: 'shopping', action: 'wishlist_toggle',
    });
  };

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
              {products.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  sessionId={sessionId}
                  wishlisted={wishlist.includes(product.id)}
                  onWishlist={toggleWishlist}
                  onAddToCart={addToCart}
                  onReserve={(p) => logEventNow(sessionId, p.id, 'click', { source: 'shopping', action: 'reserve' })}
                  formatPrice={formatPrice}
                  emoji={EMOJI_BY_CATEGORY[product.category] || '👔'}
                />
              ))}
            </AnimatePresence>
          )}

          {!loading && products.length === 0 && (
            <motion.div className="no-results" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <RiSearchLine className="no-results-icon" />
              <h3>No products found</h3>
              <p>Try adjusting your search or filters</p>
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
