import { motion } from 'framer-motion';
import {
  RiSparklingLine, RiSunLine, RiTShirtLine,
  RiCamera3Line, RiMessage3Line, RiArrowRightSLine,
  RiFireLine, RiHeartLine, RiTimeLine
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useNavigate } from 'react-router-dom';
import './Dashboard.css';

const quickActions = [
  { icon: <RiCamera3Line />, label: 'Body Scan', path: '/body-scanner', color: '#6C63FF' },
  { icon: <RiSparklingLine />, label: 'Get Styled', path: '/recommendations', color: '#00C2FF' },
  { icon: <RiMessage3Line />, label: 'AI Chat', path: '/stylist', color: '#8B5CF6' },
  { icon: <RiTShirtLine />, label: 'Try On', path: '/virtual-tryon', color: '#EC4899' },
];

const recentOutfits = [
  { id: 1, name: 'Business Casual', items: 4, date: 'Today' },
  { id: 2, name: 'Weekend Brunch', items: 3, date: 'Yesterday' },
  { id: 3, name: 'Date Night', items: 5, date: '2 days ago' },
];

const trending = [
  { id: 1, name: 'Quiet Luxury', growth: '+24%' },
  { id: 2, name: 'Coastal Grandmother', growth: '+18%' },
  { id: 3, name: 'Dark Academia', growth: '+15%' },
  { id: 4, name: 'Minimalist Chic', growth: '+12%' },
];

export default function Dashboard() {
  const navigate = useNavigate();

  return (
    <div className="dashboard">
      <motion.div
        className="dash-greeting"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1>Good Evening, <span className="gradient-text">Alex</span></h1>
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
            Based on today's weather and your schedule, I suggest a smart casual outfit
            with layering options. Want me to put something together?
          </p>
          <AnimatedButton size="small" onClick={() => navigate('/stylist')}>
            Chat with AI <RiArrowRightSLine />
          </AnimatedButton>
        </GlassCard>

        <GlassCard className="dash-weather-card" delay={0.2}>
          <div className="weather-header">
            <RiSunLine className="weather-icon" />
            <div>
              <h3>24°C</h3>
              <p>Partly Cloudy</p>
            </div>
          </div>
          <p className="weather-rec">Light layers recommended for evening cool-down</p>
        </GlassCard>

        <GlassCard className="dash-rec-card" delay={0.3}>
          <div className="rec-header">
            <h3><RiSparklingLine /> Today's Pick</h3>
            <span className="rec-badge">AI Generated</span>
          </div>
          <div className="rec-outfit">
            <div className="rec-outfit-item">
              <div className="outfit-thumb">👔</div>
              <div>
                <p className="outfit-name">Silk Blazer</p>
                <p className="outfit-brand">Gucci</p>
              </div>
            </div>
            <div className="rec-outfit-item">
              <div className="outfit-thumb">👖</div>
              <div>
                <p className="outfit-name">Tailored Trousers</p>
                <p className="outfit-brand">Prada</p>
              </div>
            </div>
            <div className="rec-outfit-item">
              <div className="outfit-thumb">👞</div>
              <div>
                <p className="outfit-name">Chelsea Boots</p>
                <p className="outfit-brand">Saint Laurent</p>
              </div>
            </div>
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
            <h3><RiTimeLine /> Recent Outfits</h3>
            <button className="see-all" onClick={() => navigate('/outfit-builder')}>See All</button>
          </div>
          <div className="recent-list">
            {recentOutfits.map((outfit) => (
              <div key={outfit.id} className="recent-item">
                <div className="recent-icon">
                  <RiTShirtLine />
                </div>
                <div className="recent-info">
                  <p className="recent-name">{outfit.name}</p>
                  <span>{outfit.items} items · {outfit.date}</span>
                </div>
                <RiArrowRightSLine className="recent-arrow" />
              </div>
            ))}
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
            <h3><RiHeartLine /> Saved Items</h3>
            <span className="fav-count">12</span>
          </div>
          <div className="favorites-preview">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="fav-thumb">
                <div className="fav-placeholder" style={{ background: `hsl(${i * 50}, 40%, 30%)` }} />
              </div>
            ))}
          </div>
          <AnimatedButton variant="ghost" size="small" fullWidth onClick={() => navigate('/shopping')}>
            View Wishlist
          </AnimatedButton>
        </GlassCard>
      </div>
    </div>
  );
}
