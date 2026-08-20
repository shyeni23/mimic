import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiSunLine,
  RiCloudLine,
  RiRainyLine,
  RiSnowflakeLine,
  RiTShirtLine,
  RiTShirt2Line,
  RiHandHeartLine,
  RiShirtLine,
  RiFootprintLine,
  RiThumbUpLine,
  RiThumbDownLine,
  RiStarLine,
  RiStarFill,
  RiMagicLine,
  RiPaletteLine,
  RiBarChartBoxLine,
  RiLightbulbLine,
  RiRefreshLine,
  RiArrowRightLine,
  RiHeartLine,
  RiTimeLine,
  RiWindyLine,
  RiTempHotLine,
  RiDropLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import './Personalization.css';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const weatherData = {
  temperature: 72,
  condition: 'Partly Cloudy',
  humidity: 45,
  wind: 12,
  icon: 'cloudy',
  forecast: 'Mild with afternoon sunshine',
};

const wardrobeCategories = [
  { name: 'Tops', count: 34, percentage: 28, color: '#6C63FF' },
  { name: 'Bottoms', count: 22, percentage: 18, color: '#00C2FF' },
  { name: 'Dresses', count: 15, percentage: 12, color: '#8B5CF6' },
  { name: 'Outerwear', count: 12, percentage: 10, color: '#F472B6' },
  { name: 'Shoes', count: 18, percentage: 15, color: '#34D399' },
  { name: 'Accessories', count: 20, percentage: 17, color: '#FBBF24' },
];

const favoriteColors = [
  { name: 'Navy Blue', hex: '#1E3A5F' },
  { name: 'Emerald', hex: '#047857' },
  { name: 'Burgundy', hex: '#7C2D3E' },
  { name: 'Cream', hex: '#F5F0E8' },
  { name: 'Charcoal', hex: '#374151' },
  { name: 'Blush', hex: '#FBC4C4' },
  { name: 'Olive', hex: '#6B7F3B' },
  { name: 'Lavender', hex: '#B794F4' },
];

const aiRecommendations = [
  {
    id: 1,
    title: 'Color Harmony Analysis',
    description:
      'Based on your skin tone analysis and past preferences, warm earth tones and jewel colors complement your complexion best. We recommend incorporating more burgundy and emerald pieces.',
    icon: RiPaletteLine,
    confidence: 94,
  },
  {
    id: 2,
    title: 'Style Pattern Recognition',
    description:
      'Your outfit choices show a preference for smart-casual combinations. You tend to pair structured tops with relaxed bottoms, creating a balanced silhouette.',
    icon: RiBarChartBoxLine,
    confidence: 89,
  },
  {
    id: 3,
    title: 'Seasonal Adaptation',
    description:
      'Transitioning to fall, we suggest layering lightweight knits over your favorite summer pieces. Your wardrobe has great layering potential with 12 compatible combinations.',
    icon: RiLightbulbLine,
    confidence: 91,
  },
];

const outfitSuggestion = {
  top: 'Light Blue Oxford Shirt',
  bottom: 'Khaki Chinos',
  shoes: 'White Leather Sneakers',
  accessory: 'Brown Leather Watch',
  reason: 'Perfect for the mild weather with a smart-casual vibe.',
};

const WeatherIcon = ({ condition }) => {
  switch (condition) {
    case 'sunny':
      return <RiSunLine />;
    case 'rainy':
      return <RiRainyLine />;
    case 'snowy':
      return <RiSnowflakeLine />;
    default:
      return <RiCloudLine />;
  }
};

const Personalization = () => {
  const [ratings, setRatings] = useState({});
  const [feedback, setFeedback] = useState({});
  const [hoveredStar, setHoveredStar] = useState({ id: null, star: 0 });
  const [refreshing, setRefreshing] = useState(false);

  const handleThumbFeedback = (recId, type) => {
    setFeedback((prev) => ({
      ...prev,
      [recId]: prev[recId] === type ? null : type,
    }));
  };

  const handleStarRating = (recId, star) => {
    setRatings((prev) => ({
      ...prev,
      [recId]: star,
    }));
  };

  const handleRefreshRecommendations = () => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 2000);
  };

  return (
    <motion.div
      className="personalization-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div className="personalization-header" variants={itemVariants}>
        <div className="header-content">
          <h1 className="page-title">
            <RiMagicLine className="title-icon" />
            Personalization
          </h1>
          <p className="page-subtitle">
            AI-powered style recommendations tailored just for you
          </p>
        </div>
        <AnimatedButton onClick={handleRefreshRecommendations}>
          <RiRefreshLine
            className={`refresh-icon ${refreshing ? 'spinning' : ''}`}
          />
          Refresh
        </AnimatedButton>
      </motion.div>

      <div className="personalization-grid">
        {/* Weather-Based Recommendations */}
        <motion.div className="weather-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiCloudLine className="section-icon" />
                Weather-Based Outfit
              </h2>
              <span className="weather-badge">Live</span>
            </div>

            <div className="weather-content">
              <div className="weather-current">
                <div className="weather-main">
                  <div className="weather-icon-large">
                    <WeatherIcon condition={weatherData.icon} />
                  </div>
                  <div className="weather-temp">
                    <span className="temp-value">{weatherData.temperature}</span>
                    <span className="temp-unit">&deg;F</span>
                  </div>
                </div>
                <div className="weather-details">
                  <span className="weather-condition">{weatherData.condition}</span>
                  <div className="weather-meta">
                    <span>
                      <RiDropLine /> {weatherData.humidity}%
                    </span>
                    <span>
                      <RiWindyLine /> {weatherData.wind} mph
                    </span>
                  </div>
                  <p className="weather-forecast">
                    <RiTimeLine /> {weatherData.forecast}
                  </p>
                </div>
              </div>

              <div className="outfit-suggestion">
                <h3>Recommended Outfit</h3>
                <div className="outfit-items">
                  <div className="outfit-item">
                    <RiShirtLine className="outfit-item-icon" />
                    <div>
                      <span className="outfit-item-label">Top</span>
                      <span className="outfit-item-name">{outfitSuggestion.top}</span>
                    </div>
                  </div>
                  <div className="outfit-item">
                    <RiTShirtLine className="outfit-item-icon" />
                    <div>
                      <span className="outfit-item-label">Bottom</span>
                      <span className="outfit-item-name">
                        {outfitSuggestion.bottom}
                      </span>
                    </div>
                  </div>
                  <div className="outfit-item">
                    <RiFootprintLine className="outfit-item-icon" />
                    <div>
                      <span className="outfit-item-label">Shoes</span>
                      <span className="outfit-item-name">{outfitSuggestion.shoes}</span>
                    </div>
                  </div>
                  <div className="outfit-item">
                    <RiHandHeartLine className="outfit-item-icon" />
                    <div>
                      <span className="outfit-item-label">Accessory</span>
                      <span className="outfit-item-name">
                        {outfitSuggestion.accessory}
                      </span>
                    </div>
                  </div>
                </div>
                <p className="outfit-reason">
                  <RiLightbulbLine /> {outfitSuggestion.reason}
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Wardrobe Analysis */}
        <motion.div className="wardrobe-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiTShirt2Line className="section-icon" />
                Wardrobe Analysis
              </h2>
              <span className="total-items">
                {wardrobeCategories.reduce((sum, c) => sum + c.count, 0)} items
              </span>
            </div>

            <div className="wardrobe-categories">
              {wardrobeCategories.map((category, index) => (
                <motion.div
                  key={category.name}
                  className="category-item"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                >
                  <div className="category-info">
                    <span className="category-name">{category.name}</span>
                    <span className="category-count">{category.count}</span>
                  </div>
                  <div className="category-bar-track">
                    <motion.div
                      className="category-bar-fill"
                      style={{ backgroundColor: category.color }}
                      initial={{ width: 0 }}
                      animate={{ width: `${category.percentage}%` }}
                      transition={{ duration: 1, delay: index * 0.1 }}
                    />
                  </div>
                  <span className="category-percentage">
                    {category.percentage}%
                  </span>
                </motion.div>
              ))}
            </div>
          </GlassCard>
        </motion.div>

        {/* Favorite Colors */}
        <motion.div className="colors-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiPaletteLine className="section-icon" />
                Favorite Colors
              </h2>
            </div>

            <div className="colors-grid">
              {favoriteColors.map((color, index) => (
                <motion.div
                  key={color.name}
                  className="color-item"
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.95 }}
                  initial={{ opacity: 0, scale: 0 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: index * 0.08 }}
                >
                  <div
                    className="color-circle"
                    style={{ backgroundColor: color.hex }}
                  >
                    <span className="color-hex">{color.hex}</span>
                  </div>
                  <span className="color-name">{color.name}</span>
                </motion.div>
              ))}
            </div>
          </GlassCard>
        </motion.div>

        {/* AI Recommendation Explanations */}
        <motion.div className="ai-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiMagicLine className="section-icon" />
                AI Insights
              </h2>
            </div>

            <div className="ai-recommendations">
              <AnimatePresence>
                {aiRecommendations.map((rec) => {
                  const IconComponent = rec.icon;
                  return (
                    <motion.div
                      key={rec.id}
                      className="recommendation-card"
                      layout
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -20 }}
                    >
                      <div className="rec-header">
                        <div className="rec-icon-wrapper">
                          <IconComponent />
                        </div>
                        <div className="rec-title-area">
                          <h3>{rec.title}</h3>
                          <div className="confidence-badge">
                            <RiTempHotLine />
                            {rec.confidence}% confidence
                          </div>
                        </div>
                      </div>
                      <p className="rec-description">{rec.description}</p>

                      {/* Feedback for this recommendation */}
                      <div className="rec-feedback">
                        <div className="thumb-buttons">
                          <button
                            className={`thumb-btn ${
                              feedback[rec.id] === 'up' ? 'active-up' : ''
                            }`}
                            onClick={() => handleThumbFeedback(rec.id, 'up')}
                            aria-label="Thumbs up"
                          >
                            <RiThumbUpLine />
                          </button>
                          <button
                            className={`thumb-btn ${
                              feedback[rec.id] === 'down' ? 'active-down' : ''
                            }`}
                            onClick={() => handleThumbFeedback(rec.id, 'down')}
                            aria-label="Thumbs down"
                          >
                            <RiThumbDownLine />
                          </button>
                        </div>
                        <div className="star-rating">
                          {[1, 2, 3, 4, 5].map((star) => (
                            <button
                              key={star}
                              className={`star-btn ${
                                star <=
                                (hoveredStar.id === rec.id
                                  ? hoveredStar.star
                                  : ratings[rec.id] || 0)
                                  ? 'star-filled'
                                  : ''
                              }`}
                              onClick={() => handleStarRating(rec.id, star)}
                              onMouseEnter={() =>
                                setHoveredStar({ id: rec.id, star })
                              }
                              onMouseLeave={() =>
                                setHoveredStar({ id: null, star: 0 })
                              }
                              aria-label={`Rate ${star} stars`}
                            >
                              {star <=
                              (hoveredStar.id === rec.id
                                ? hoveredStar.star
                                : ratings[rec.id] || 0) ? (
                                <RiStarFill />
                              ) : (
                                <RiStarLine />
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          </GlassCard>
        </motion.div>

        {/* Overall Feedback Section */}
        <motion.div className="feedback-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiHeartLine className="section-icon" />
                How are we doing?
              </h2>
            </div>

            <div className="feedback-content">
              <p className="feedback-prompt">
                Help us improve your personalized experience by rating our
                recommendations.
              </p>

              <div className="feedback-overall-stars">
                {[1, 2, 3, 4, 5].map((star) => (
                  <motion.button
                    key={star}
                    className={`overall-star ${
                      star <=
                      (hoveredStar.id === 'overall'
                        ? hoveredStar.star
                        : ratings.overall || 0)
                        ? 'star-filled'
                        : ''
                    }`}
                    onClick={() => handleStarRating('overall', star)}
                    onMouseEnter={() =>
                      setHoveredStar({ id: 'overall', star })
                    }
                    onMouseLeave={() =>
                      setHoveredStar({ id: null, star: 0 })
                    }
                    whileHover={{ scale: 1.2 }}
                    whileTap={{ scale: 0.9 }}
                  >
                    {star <=
                    (hoveredStar.id === 'overall'
                      ? hoveredStar.star
                      : ratings.overall || 0) ? (
                      <RiStarFill />
                    ) : (
                      <RiStarLine />
                    )}
                  </motion.button>
                ))}
              </div>

              {ratings.overall && (
                <motion.p
                  className="feedback-thanks"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  Thank you for your feedback! Your rating helps us personalize
                  your experience even further.
                </motion.p>
              )}

              <div className="feedback-actions">
                <AnimatedButton>
                  <RiArrowRightLine /> Submit Detailed Feedback
                </AnimatedButton>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default Personalization;
