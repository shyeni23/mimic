import React, { useState, useMemo } from 'react';
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
  RiFireLine,
  RiPriceTag3Line,
  RiStarFill,
  RiTruckLine,
  RiShieldCheckLine,
  RiFilterLine,
  RiSparkling2Line,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import FilterChips from '../components/Common/FilterChips';
import './Shopping.css';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
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

const filterOptions = ['All', 'New Arrivals', 'Trending', 'Sale'];

const products = [
  {
    id: 1,
    name: 'Cashmere Blend Overcoat',
    brand: 'Maison Laurent',
    price: 489.00,
    originalPrice: null,
    rating: 4.8,
    reviews: 124,
    category: 'New Arrivals',
    badge: 'New',
    image: null,
  },
  {
    id: 2,
    name: 'Italian Leather Chelsea Boots',
    brand: 'Artisan & Co.',
    price: 325.00,
    originalPrice: null,
    rating: 4.9,
    reviews: 89,
    category: 'Trending',
    badge: 'Trending',
    image: null,
  },
  {
    id: 3,
    name: 'Silk Blend Evening Dress',
    brand: 'Ethereal',
    price: 279.00,
    originalPrice: 399.00,
    rating: 4.7,
    reviews: 56,
    category: 'Sale',
    badge: 'Sale',
    image: null,
  },
  {
    id: 4,
    name: 'Merino Wool Turtleneck',
    brand: 'Nordic Essentials',
    price: 165.00,
    originalPrice: null,
    rating: 4.6,
    reviews: 203,
    category: 'Trending',
    badge: 'Trending',
    image: null,
  },
  {
    id: 5,
    name: 'Tailored Slim Fit Blazer',
    brand: 'Savile & Row',
    price: 395.00,
    originalPrice: 550.00,
    rating: 4.8,
    reviews: 167,
    category: 'Sale',
    badge: 'Sale',
    image: null,
  },
  {
    id: 6,
    name: 'Premium Denim Jeans',
    brand: 'Indigo Theory',
    price: 189.00,
    originalPrice: null,
    rating: 4.5,
    reviews: 312,
    category: 'New Arrivals',
    badge: 'New',
    image: null,
  },
  {
    id: 7,
    name: 'Linen Summer Shirt',
    brand: 'Coastal Studio',
    price: 125.00,
    originalPrice: null,
    rating: 4.4,
    reviews: 98,
    category: 'Trending',
    badge: null,
    image: null,
  },
  {
    id: 8,
    name: 'Handcrafted Leather Belt',
    brand: 'Heritage Craft',
    price: 89.00,
    originalPrice: 120.00,
    rating: 4.7,
    reviews: 445,
    category: 'Sale',
    badge: 'Sale',
    image: null,
  },
  {
    id: 9,
    name: 'Velvet Lounge Robe',
    brand: 'Luxe Home',
    price: 210.00,
    originalPrice: null,
    rating: 4.9,
    reviews: 76,
    category: 'New Arrivals',
    badge: 'New',
    image: null,
  },
  {
    id: 10,
    name: 'Structured Canvas Tote',
    brand: 'Modern Carry',
    price: 145.00,
    originalPrice: null,
    rating: 4.3,
    reviews: 189,
    category: 'Trending',
    badge: null,
    image: null,
  },
  {
    id: 11,
    name: 'Alpaca Wool Scarf',
    brand: 'Andean Luxe',
    price: 95.00,
    originalPrice: 140.00,
    rating: 4.6,
    reviews: 234,
    category: 'Sale',
    badge: 'Sale',
    image: null,
  },
  {
    id: 12,
    name: 'Suede Ankle Boots',
    brand: 'Terrain Walk',
    price: 275.00,
    originalPrice: null,
    rating: 4.8,
    reviews: 112,
    category: 'New Arrivals',
    badge: 'New',
    image: null,
  },
];

const Shopping = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('All');
  const [cart, setCart] = useState([]);
  const [wishlist, setWishlist] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);

  const filteredProducts = useMemo(() => {
    let filtered = products;

    if (activeFilter !== 'All') {
      filtered = filtered.filter((p) => p.category === activeFilter);
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (p) =>
          p.name.toLowerCase().includes(query) ||
          p.brand.toLowerCase().includes(query)
      );
    }

    return filtered;
  }, [activeFilter, searchQuery]);

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
    setWishlist((prev) =>
      prev.includes(productId)
        ? prev.filter((id) => id !== productId)
        : [...prev, productId]
    );
  };

  const cartTotal = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
  const cartItemCount = cart.reduce((sum, item) => sum + item.quantity, 0);

  const getBadgeClass = (badge) => {
    switch (badge) {
      case 'New':
        return 'badge-new';
      case 'Trending':
        return 'badge-trending';
      case 'Sale':
        return 'badge-sale';
      default:
        return '';
    }
  };

  const getBadgeIcon = (badge) => {
    switch (badge) {
      case 'New':
        return <RiSparkling2Line />;
      case 'Trending':
        return <RiFireLine />;
      case 'Sale':
        return <RiPriceTag3Line />;
      default:
        return null;
    }
  };

  return (
    <motion.div
      className="shopping-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {/* Header */}
      <motion.div className="shopping-header" variants={itemVariants}>
        <div className="header-content">
          <h1 className="page-title">
            <RiShoppingBag3Line className="title-icon" />
            Shopping
          </h1>
          <p className="page-subtitle">
            Curated premium fashion, handpicked for your style
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

      {/* Search & Filters */}
      <motion.div className="shopping-controls" variants={itemVariants}>
        <div className="search-bar">
          <RiSearchLine className="search-icon" />
          <input
            type="text"
            placeholder="Search products, brands..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          {searchQuery && (
            <button
              className="search-clear"
              onClick={() => setSearchQuery('')}
            >
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
      </motion.div>

      {/* Main Content */}
      <div className={`shopping-content ${cartOpen ? 'cart-visible' : ''}`}>
        {/* Product Grid */}
        <div className="product-grid">
          <AnimatePresence mode="popLayout">
            {filteredProducts.map((product) => (
              <motion.div
                key={product.id}
                className="product-card"
                variants={cardVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                layout
                whileHover={{ y: -4 }}
              >
                {/* Product Image Placeholder */}
                <div className="product-image">
                  <div className="image-placeholder">
                    <RiShoppingBag3Line className="placeholder-icon" />
                  </div>
                  {product.badge && (
                    <span className={`product-badge ${getBadgeClass(product.badge)}`}>
                      {getBadgeIcon(product.badge)}
                      {product.badge}
                    </span>
                  )}
                  <button
                    className={`wishlist-btn ${
                      wishlist.includes(product.id) ? 'wishlisted' : ''
                    }`}
                    onClick={() => toggleWishlist(product.id)}
                    aria-label="Toggle wishlist"
                  >
                    {wishlist.includes(product.id) ? (
                      <RiHeartFill />
                    ) : (
                      <RiHeartLine />
                    )}
                  </button>
                </div>

                {/* Product Info */}
                <div className="product-info">
                  <span className="product-brand">{product.brand}</span>
                  <h3 className="product-name">{product.name}</h3>
                  <div className="product-rating">
                    <RiStarFill className="star-icon" />
                    <span className="rating-value">{product.rating}</span>
                    <span className="review-count">({product.reviews})</span>
                  </div>
                  <div className="product-price">
                    <span className="current-price">
                      ${product.price.toFixed(2)}
                    </span>
                    {product.originalPrice && (
                      <span className="original-price">
                        ${product.originalPrice.toFixed(2)}
                      </span>
                    )}
                    {product.originalPrice && (
                      <span className="discount-badge">
                        {Math.round(
                          ((product.originalPrice - product.price) /
                            product.originalPrice) *
                            100
                        )}
                        % OFF
                      </span>
                    )}
                  </div>
                </div>

                {/* Product Actions */}
                <div className="product-actions">
                  <button
                    className="action-btn reserve-btn"
                    onClick={() => {}}
                  >
                    <RiStoreLine />
                    Reserve in Store
                  </button>
                  <button
                    className="action-btn cart-btn"
                    onClick={() => addToCart(product)}
                  >
                    <RiShoppingCartLine />
                    Add to Cart
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {filteredProducts.length === 0 && (
            <motion.div
              className="no-results"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <RiSearchLine className="no-results-icon" />
              <h3>No products found</h3>
              <p>Try adjusting your search or filters</p>
            </motion.div>
          )}
        </div>

        {/* Cart Sidebar */}
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
                  <h2>
                    <RiShoppingCartLine />
                    Your Cart
                  </h2>
                  <button
                    className="cart-close"
                    onClick={() => setCartOpen(false)}
                  >
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
                              <RiShoppingBag3Line />
                            </div>
                            <div className="cart-item-details">
                              <span className="cart-item-name">{item.name}</span>
                              <span className="cart-item-brand">{item.brand}</span>
                              <span className="cart-item-price">
                                ${(item.price * item.quantity).toFixed(2)}
                              </span>
                            </div>
                            <div className="cart-item-controls">
                              <button
                                className="qty-btn"
                                onClick={() => updateCartQuantity(item.id, -1)}
                              >
                                <RiSubtractLine />
                              </button>
                              <span className="qty-value">{item.quantity}</span>
                              <button
                                className="qty-btn"
                                onClick={() => updateCartQuantity(item.id, 1)}
                              >
                                <RiAddLine />
                              </button>
                              <button
                                className="remove-btn"
                                onClick={() => removeFromCart(item.id)}
                              >
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
                      <div className="cart-summary-row">
                        <span>Subtotal</span>
                        <span>${cartTotal.toFixed(2)}</span>
                      </div>
                      <div className="cart-summary-row">
                        <span>Shipping</span>
                        <span className="free-shipping">Free</span>
                      </div>
                      <div className="cart-summary-total">
                        <span>Total</span>
                        <span>${cartTotal.toFixed(2)}</span>
                      </div>

                      <AnimatedButton className="checkout-btn">
                        <RiArrowRightLine /> Checkout
                      </AnimatedButton>

                      <div className="cart-trust-badges">
                        <span>
                          <RiTruckLine /> Free Returns
                        </span>
                        <span>
                          <RiShieldCheckLine /> Secure Checkout
                        </span>
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
