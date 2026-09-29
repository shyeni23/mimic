import React, { useState } from 'react';
import { motion } from 'framer-motion';
import {
  RiUserLine,
  RiRulerLine,
  RiBodyScanLine,
  RiPaletteLine,
  RiCalendarLine,
  RiCheckLine,
  RiCameraLine,
  RiGridLine,
  RiSparklingLine,
  RiEyeLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useSession } from '../context/SessionContext';
import { useNavigate } from 'react-router-dom';
import './Profile.css';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const stylePreferences = [
  'Smart Casual', 'Minimalist', 'Bohemian', 'Classic',
  'Streetwear', 'Athleisure', 'Vintage', 'Scandinavian',
  'Preppy', 'Edgy',
];

const Profile = () => {
  const { scanData, sessionId } = useSession();
  const navigate = useNavigate();
  const [selectedTags, setSelectedTags] = useState(['Smart Casual', 'Minimalist', 'Classic']);

  const toggleTag = (tag) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const scanMeasurements = scanData ? [
    scanData.height_cm && { id: 'height', label: 'Height', value: `${Math.round(scanData.height_cm)}`, unit: 'cm', icon: RiRulerLine },
    scanData.body_shape && { id: 'body', label: 'Body Shape', value: scanData.body_shape, unit: '', icon: RiBodyScanLine },
    scanData.face_shape && { id: 'face', label: 'Face Shape', value: scanData.face_shape, unit: '', icon: RiEyeLine },
    scanData.skin_tone_category && { id: 'skin', label: 'Skin Tone', value: scanData.skin_tone_category, unit: '', icon: RiPaletteLine },
    scanData.skin_tone_undertone && { id: 'undertone', label: 'Undertone', value: scanData.skin_tone_undertone, unit: '', icon: RiSparklingLine },
    scanData.gender && { id: 'gender', label: 'Detected Gender', value: scanData.gender, unit: '', icon: RiUserLine },
    scanData.glasses_detected != null && { id: 'glasses', label: 'Glasses', value: scanData.glasses_detected ? 'Yes' : 'No', unit: '', icon: RiEyeLine },
  ].filter(Boolean) : [];

  return (
    <motion.div
      className="profile-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div className="profile-header-section" variants={itemVariants}>
        <GlassCard>
          <div className="profile-header">
            <div className="profile-avatar-area">
              <div className="avatar-container">
                <div className="avatar">
                  {scanData?.skin_tone_hex ? (
                    <div
                      className="avatar-color-swatch"
                      style={{ backgroundColor: scanData.skin_tone_hex }}
                    />
                  ) : (
                    <RiUserLine className="avatar-icon" />
                  )}
                </div>
                <button className="avatar-edit" aria-label="Take new scan" onClick={() => navigate('/body-scanner')}>
                  <RiCameraLine />
                </button>
              </div>

              <div className="profile-info">
                <h1 className="profile-name">Your Profile</h1>
                <div className="profile-details">
                  <span className="profile-detail">
                    <RiCalendarLine /> Session {sessionId ? sessionId.slice(0, 8) : '—'}
                  </span>
                  {scanData && (
                    <span className="profile-detail">
                      <RiBodyScanLine /> Scan complete
                    </span>
                  )}
                </div>
              </div>
            </div>

            <AnimatedButton onClick={() => navigate('/body-scanner')}>
              <RiCameraLine /> {scanData ? 'Rescan' : 'Start Scan'}
            </AnimatedButton>
          </div>

          <div className="profile-stats">
            <div className="stat-item">
              <span className="stat-value">{scanMeasurements.length}</span>
              <span className="stat-label">Measurements</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{selectedTags.length}</span>
              <span className="stat-label">Style Prefs</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{scanData ? '✓' : '—'}</span>
              <span className="stat-label">Scan Status</span>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      <div className="profile-grid">
        <motion.div className="measurements-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiRulerLine className="section-icon" />
                Measurements
              </h2>
              <button className="icon-action edit" onClick={() => navigate('/body-scanner')}>
                <RiCameraLine />
              </button>
            </div>

            {scanMeasurements.length > 0 ? (
              <div className="measurements-grid">
                {scanMeasurements.map((measurement, index) => {
                  const IconComponent = measurement.icon;
                  return (
                    <motion.div
                      key={measurement.id}
                      className="measurement-card"
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: index * 0.08 }}
                      whileHover={{ scale: 1.03 }}
                    >
                      <div className="measurement-icon">
                        <IconComponent />
                      </div>
                      <span className="measurement-label">{measurement.label}</span>
                      <span className="measurement-value">{measurement.value}</span>
                      {measurement.unit && (
                        <span className="measurement-unit">{measurement.unit}</span>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            ) : (
              <div className="no-scan-message">
                <RiBodyScanLine className="no-scan-icon" />
                <p>No scan data yet</p>
                <span>Complete a body scan to see your measurements here</span>
                <AnimatedButton size="small" onClick={() => navigate('/body-scanner')}>
                  <RiCameraLine /> Start Scan
                </AnimatedButton>
              </div>
            )}
          </GlassCard>
        </motion.div>

        <motion.div className="preferences-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiPaletteLine className="section-icon" />
                Style Preferences
              </h2>
            </div>

            <div className="style-tags">
              {stylePreferences.map((tag) => (
                <motion.button
                  key={tag}
                  className={`style-tag ${selectedTags.includes(tag) ? 'tag-active' : ''}`}
                  onClick={() => toggleTag(tag)}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  {selectedTags.includes(tag) && <RiCheckLine />}
                  {tag}
                </motion.button>
              ))}
            </div>
          </GlassCard>
        </motion.div>

        {scanData?.skin_tone_hex && (
          <motion.div className="outfits-section" variants={itemVariants}>
            <GlassCard>
              <div className="section-header">
                <h2>
                  <RiGridLine className="section-icon" />
                  Your Colors
                </h2>
              </div>
              <div className="color-profile">
                <div className="color-swatch-large" style={{ backgroundColor: scanData.skin_tone_hex }}>
                  <span>{scanData.skin_tone_hex}</span>
                </div>
                <div className="color-details">
                  <p><strong>Category:</strong> {scanData.skin_tone_category || 'Unknown'}</p>
                  <p><strong>Undertone:</strong> {scanData.skin_tone_undertone || 'Unknown'}</p>
                </div>
              </div>
            </GlassCard>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
};

export default Profile;
