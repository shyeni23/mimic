import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  RiSparklingLine, RiSunLine, RiMoonLine, RiTShirtLine,
  RiCamera3Line, RiMessage3Line, RiArrowRightSLine,
  RiFireLine, RiHeartLine, RiTimeLine, RiShoppingBag3Line
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useNavigate } from 'react-router-dom';
import { useSession } from '../context/SessionContext';
import { apiGetJSON } from '../utils/api';
import './Dashboard.css';

const EMOJI_BY_CATEGORY = {
  top: '👕', bottom: '👖', dress: '👗', footwear: '👟',
  bag: '👜', jewelry: '💍', watch: '⌚', accessory: '🧣',
};

const quickActions = [
  { icon: <RiCamera3Line />, label: 'Body Scan', path: '/body-scanner', color: '#6C63FF' },
  { icon: <RiSparklingLine />, label: 'Get Styled', path: '/recommendations', color: '#00C2FF' },
  { icon: <RiMessage3Line />, label: 'AI Chat', path: '/stylist', color: '#8B5CF6' },
  { icon: <RiTShirtLine />, label: 'Try On', path: '/virtual-tryon', color: '#EC4899' },
];

const trending = [
  { id: 1, name: 'Quiet Luxury', growth: '+24%' },
  { id: 2, name: 'Coastal Grandmother', growth: '+18%' },
  { id: 3, name: 'Dark Academia', growth: '+15%' },
  { id: 4, name: 'Minimalist Chic', growth: '+12%' },
];

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good Morning';
  if (h < 17) return 'Good Afternoon';
  return 'Good Evening';
}

function getWeatherIcon() {
  const h = new Date().getHours();
  if (h >= 6 && h < 18) return <RiSunLine className="weather-icon" />;
  return <RiMoonLine className="weather-icon" />;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { scanData } = useSession();
  const [featuredItems, setFeaturedItems] = useState([]);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGetJSON('/api/inventory/browse?limit=3');
        setFeaturedItems(data.items || []);
      } catch {
        setFeaturedItems([]);
      }
    })();
  }, []);

  return (
    <div className="dashboard">
      <motion.div
        className="dash-greeting"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1>{getGreeting()}, <span className="gradient-text">there</span></h1>
          <p>Here's your style intelligence for today</p>
        </div>
        <AnimatedButton size="small" onClick={() => navigate('/body-scanner')}>
          <RiCamera3Line /> Start Scan
        </AnimatedButton>
      </motion.div>

      <div className="dash-grid">
        <GlassCard className="dash-ai-card" glow delay={0.1}>
          <div className="ai-card-header">
            <div className="ai-avatar">
              <RiSparklingLine />
            </div>
            <div>
              <h3>AI Style Assistant</h3>
              <p>Ready to help</p>
            </div>
          </div>
          <p className="ai-suggestion">
            {scanData
              ? `Your profile is ready — I know your body shape and colors. Want me to find something that suits you?`
              : `Start with a quick body scan so I can learn your shape and colors, then I'll put outfits together for you.`}
          </p>
          <AnimatedButton size="small" onClick={() => navigate('/stylist')}>
            Chat with AI <RiArrowRightSLine />
          </AnimatedButton>
        </GlassCard>

        <GlassCard className="dash-weather-card" delay={0.2}>
          <div className="weather-header">
            {getWeatherIcon()}
            <div>
              <h3>{new Date().toLocaleDateString('en-US', { weekday: 'long' })}</h3>
              <p>{new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric' })}</p>
            </div>
          </div>
          <p className="weather-rec">
            {scanData?.skin_tone_category
              ? `Your ${scanData.skin_tone_category} skin tone pairs well with complementary colors.`
              : 'Scan your profile to get personalized color recommendations.'}
          </p>
        </GlassCard>

        <GlassCard className="dash-rec-card" delay={0.3}>
          <div className="rec-header">
            <h3><RiSparklingLine /> Today's Pick</h3>
            <span className="rec-badge">From Inventory</span>
          </div>
          <div className="rec-outfit">
            {featuredItems.length > 0 ? featuredItems.map((item) => (
              <div key={item.id} className="rec-outfit-item">
                <div className="outfit-thumb">
                  {item.image_url ? (
                    <img src={item.image_url} alt={item.name} className="outfit-thumb-img" />
                  ) : (
                    EMOJI_BY_CATEGORY[item.category] || '👔'
                  )}
                </div>
                <div>
                  <p className="outfit-name">{item.name}</p>
                  <p className="outfit-brand">{item.category}{item.price ? ` · ₹${item.price}` : ''}</p>
                </div>
              </div>
            )) : (
              <p style={{ opacity: 0.6, fontSize: '0.9rem' }}>Loading inventory...</p>
            )}
          </div>
          <AnimatedButton variant="secondary" size="small" fullWidth onClick={() => navigate('/recommendations')}>
            View Full Recommendation
          </AnimatedButton>
        </GlassCard>
      </div>

      <div className="dash-actions-section">
        <h2>Quick Actions</h2>
        <div className="dash-actions-grid">
          {quickActions.map((action, i) => (
            <motion.div
              key={action.label}
              className="action-card"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 + i * 0.1 }}
              whileHover={{ y: -6, scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => navigate(action.path)}
            >
              <div className="action-icon" style={{ background: `${action.color}20`, color: action.color }}>
                {action.icon}
              </div>
              <span>{action.label}</span>
            </motion.div>
          ))}
        </div>
      </div>

      <div className="dash-bottom-grid">
        <GlassCard className="dash-recent" delay={0.5}>
          <div className="section-title">
            <h3><RiTimeLine /> Your Scan Profile</h3>
            <button className="see-all" onClick={() => navigate('/body-scanner')}>New Scan</button>
          </div>
          <div className="recent-list">
            {scanData ? (
              <>
                {scanData.face_shape && (
                  <div className="recent-item">
                    <div className="recent-icon"><RiCamera3Line /></div>
                    <div className="recent-info">
                      <p className="recent-name">Face Shape</p>
                      <span>{scanData.face_shape}</span>
                    </div>
                  </div>
                )}
                {scanData.body_shape && (
                  <div className="recent-item">
                    <div className="recent-icon"><RiTShirtLine /></div>
                    <div className="recent-info">
                      <p className="recent-name">Body Shape</p>
                      <span>{scanData.body_shape}</span>
                    </div>
                  </div>
                )}
                {scanData.skin_tone_category && (
                  <div className="recent-item">
                    <div className="recent-icon"><RiSparklingLine /></div>
                    <div className="recent-info">
                      <p className="recent-name">Skin Tone</p>
                      <span>{scanData.skin_tone_category} ({scanData.skin_tone_undertone || 'unknown'} undertone)</span>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="recent-item">
                <div className="recent-icon"><RiCamera3Line /></div>
                <div className="recent-info">
                  <p className="recent-name">No scan yet</p>
                  <span>Start a body scan to build your profile</span>
                </div>
              </div>
            )}
          </div>
        </GlassCard>

        <GlassCard className="dash-trending" delay={0.6}>
          <div className="section-title">
            <h3><RiFireLine /> Trending Styles</h3>
            <button className="see-all" onClick={() => navigate('/shopping')}>Explore</button>
          </div>
          <div className="trending-list">
            {trending.map((item, i) => (
              <div key={item.id} className="trending-item">
                <span className="trending-rank">#{i + 1}</span>
                <p className="trending-name">{item.name}</p>
                <span className="trending-growth">{item.growth}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard className="dash-favorites" delay={0.7}>
          <div className="section-title">
            <h3><RiHeartLine /> Quick Links</h3>
          </div>
          <div className="favorites-preview">
            <motion.div className="fav-link" whileHover={{ scale: 1.05 }} onClick={() => navigate('/shopping')}>
              <RiShoppingBag3Line /> Browse Store
            </motion.div>
            <motion.div className="fav-link" whileHover={{ scale: 1.05 }} onClick={() => navigate('/outfit-builder')}>
              <RiTShirtLine /> Build Outfit
            </motion.div>
            <motion.div className="fav-link" whileHover={{ scale: 1.05 }} onClick={() => navigate('/staff-requests')}>
              <RiMessage3Line /> Staff Help
            </motion.div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
