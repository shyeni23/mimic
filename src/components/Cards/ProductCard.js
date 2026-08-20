import { useState } from 'react';
import { motion } from 'framer-motion';
import { RiHeartLine, RiHeartFill, RiShoppingCartLine, RiSparklingLine } from 'react-icons/ri';
import './ProductCard.css';

export default function ProductCard({ product, onAddToCart, onToggleFavorite, delay = 0 }) {
  const [isFavorite, setIsFavorite] = useState(false);

  const handleFavorite = () => {
    setIsFavorite(!isFavorite);
    onToggleFavorite?.(product.id);
  };

  const gradients = [
    'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
    'linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)',
  ];

  return (
    <motion.div
      className="product-card"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      whileHover={{ y: -6 }}
    >
      <div
        className="product-image"
        style={{ background: gradients[(product.id - 1) % gradients.length] }}
      >
        <span className="product-emoji">
          {product.category === 'top' ? '👔' :
           product.category === 'bottom' ? '👖' :
           product.category === 'shoes' ? '👞' :
           product.category === 'bag' ? '👜' :
           product.category === 'watch' ? '⌚' : '💍'}
        </span>
        <motion.button
          className={`fav-btn ${isFavorite ? 'active' : ''}`}
          onClick={handleFavorite}
          whileHover={{ scale: 1.2 }}
          whileTap={{ scale: 0.8 }}
        >
          {isFavorite ? <RiHeartFill /> : <RiHeartLine />}
        </motion.button>
        {product.confidence && (
          <div className="confidence-badge">
            <RiSparklingLine /> {product.confidence}% Match
          </div>
        )}
      </div>

      <div className="product-info">
        <p className="product-brand">{product.brand}</p>
        <h4 className="product-name">{product.name}</h4>

        <div className="product-meta">
          <span className="product-size">Size: {product.size}</span>
          <span className="product-color">
            <span className="color-dot" style={{ background: product.color === 'Black' ? '#333' : product.color === 'Navy' ? '#1e3a5f' : product.color === 'Charcoal' ? '#4a4a4a' : product.color === 'Cream' ? '#fdf5e6' : product.color === 'Brown' ? '#8B4513' : '#333' }} />
            {product.color}
          </span>
        </div>

        {product.reason && (
          <p className="product-reason">
            <RiSparklingLine /> {product.reason}
          </p>
        )}

        <div className="product-footer">
          <span className="product-price">${product.price?.toLocaleString()}</span>
          <motion.button
            className="add-cart-btn"
            onClick={() => onAddToCart?.(product)}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <RiShoppingCartLine /> Add
          </motion.button>
        </div>
      </div>
    </motion.div>
  );
}
