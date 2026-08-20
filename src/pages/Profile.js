import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiUserLine,
  RiEditLine,
  RiSaveLine,
  RiCloseLine,
  RiRulerLine,
  RiScalesLine,
  RiBodyScanLine,
  RiShirtLine,
  RiHeartLine,
  RiPaletteLine,
  RiHistoryLine,
  RiShoppingBag3Line,
  RiImageLine,
  RiCalendarLine,
  RiPriceTag3Line,
  RiCheckLine,
  RiCameraLine,
  RiMailLine,
  RiMapPinLine,
  RiStarLine,
  RiGridLine,
  RiAddLine,
  RiDeleteBinLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import './Profile.css';

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

const initialProfile = {
  name: 'Alexandra Chen',
  email: 'alexandra.chen@email.com',
  location: 'San Francisco, CA',
  memberSince: 'January 2024',
  avatar: null,
};

const initialMeasurements = [
  { id: 'height', label: 'Height', value: "5'7\"", unit: 'ft/in', icon: RiRulerLine },
  { id: 'weight', label: 'Weight', value: '135', unit: 'lbs', icon: RiScalesLine },
  { id: 'chest', label: 'Chest', value: '36', unit: 'in', icon: RiBodyScanLine },
  { id: 'waist', label: 'Waist', value: '28', unit: 'in', icon: RiShirtLine },
  { id: 'hips', label: 'Hips', value: '38', unit: 'in', icon: RiBodyScanLine },
];

const stylePreferences = [
  'Smart Casual',
  'Minimalist',
  'Bohemian',
  'Classic',
  'Streetwear',
  'Athleisure',
  'Vintage',
  'Scandinavian',
  'Preppy',
  'Edgy',
];

const purchaseHistory = [
  {
    id: 1,
    name: 'Cashmere Blend Overcoat',
    brand: 'Maison Laurent',
    price: 489.0,
    date: '2024-11-15',
    status: 'Delivered',
  },
  {
    id: 2,
    name: 'Italian Leather Chelsea Boots',
    brand: 'Artisan & Co.',
    price: 325.0,
    date: '2024-10-28',
    status: 'Delivered',
  },
  {
    id: 3,
    name: 'Silk Blend Evening Dress',
    brand: 'Ethereal',
    price: 279.0,
    date: '2024-10-05',
    status: 'Delivered',
  },
  {
    id: 4,
    name: 'Merino Wool Turtleneck',
    brand: 'Nordic Essentials',
    price: 165.0,
    date: '2024-09-20',
    status: 'Returned',
  },
  {
    id: 5,
    name: 'Tailored Slim Fit Blazer',
    brand: 'Savile & Row',
    price: 395.0,
    date: '2024-09-01',
    status: 'Delivered',
  },
];

const savedOutfits = [
  { id: 1, name: 'Office Power Look', items: 4, season: 'Fall', favorite: true },
  { id: 2, name: 'Weekend Brunch', items: 3, season: 'Spring', favorite: false },
  { id: 3, name: 'Date Night', items: 5, season: 'All', favorite: true },
  { id: 4, name: 'Casual Friday', items: 3, season: 'Summer', favorite: false },
  { id: 5, name: 'Travel Capsule', items: 6, season: 'All', favorite: true },
  { id: 6, name: 'Gym to Street', items: 4, season: 'All', favorite: false },
];

const Profile = () => {
  const [profile, setProfile] = useState(initialProfile);
  const [measurements, setMeasurements] = useState(initialMeasurements);
  const [editingProfile, setEditingProfile] = useState(false);
  const [editingMeasurements, setEditingMeasurements] = useState(false);
  const [selectedTags, setSelectedTags] = useState([
    'Smart Casual',
    'Minimalist',
    'Classic',
    'Scandinavian',
  ]);
  const [tempProfile, setTempProfile] = useState(initialProfile);
  const [tempMeasurements, setTempMeasurements] = useState(initialMeasurements);

  const handleEditProfile = () => {
    setTempProfile({ ...profile });
    setEditingProfile(true);
  };

  const handleSaveProfile = () => {
    setProfile({ ...tempProfile });
    setEditingProfile(false);
  };

  const handleCancelProfileEdit = () => {
    setEditingProfile(false);
  };

  const handleEditMeasurements = () => {
    setTempMeasurements([...measurements.map((m) => ({ ...m }))]);
    setEditingMeasurements(true);
  };

  const handleSaveMeasurements = () => {
    setMeasurements([...tempMeasurements]);
    setEditingMeasurements(false);
  };

  const handleCancelMeasurementsEdit = () => {
    setEditingMeasurements(false);
  };

  const updateMeasurement = (id, value) => {
    setTempMeasurements((prev) =>
      prev.map((m) => (m.id === id ? { ...m, value } : m))
    );
  };

  const toggleTag = (tag) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'Delivered':
        return 'status-delivered';
      case 'Returned':
        return 'status-returned';
      case 'Processing':
        return 'status-processing';
      default:
        return '';
    }
  };

  return (
    <motion.div
      className="profile-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {/* Profile Header */}
      <motion.div className="profile-header-section" variants={itemVariants}>
        <GlassCard>
          <div className="profile-header">
            <div className="profile-avatar-area">
              <div className="avatar-container">
                <div className="avatar">
                  <RiUserLine className="avatar-icon" />
                </div>
                <button className="avatar-edit" aria-label="Change photo">
                  <RiCameraLine />
                </button>
              </div>

              <div className="profile-info">
                {editingProfile ? (
                  <div className="profile-edit-form">
                    <input
                      type="text"
                      value={tempProfile.name}
                      onChange={(e) =>
                        setTempProfile({ ...tempProfile, name: e.target.value })
                      }
                      className="profile-input"
                      placeholder="Full Name"
                    />
                    <input
                      type="email"
                      value={tempProfile.email}
                      onChange={(e) =>
                        setTempProfile({ ...tempProfile, email: e.target.value })
                      }
                      className="profile-input"
                      placeholder="Email"
                    />
                    <input
                      type="text"
                      value={tempProfile.location}
                      onChange={(e) =>
                        setTempProfile({
                          ...tempProfile,
                          location: e.target.value,
                        })
                      }
                      className="profile-input"
                      placeholder="Location"
                    />
                    <div className="profile-edit-actions">
                      <AnimatedButton onClick={handleSaveProfile}>
                        <RiSaveLine /> Save
                      </AnimatedButton>
                      <button
                        className="cancel-btn"
                        onClick={handleCancelProfileEdit}
                      >
                        <RiCloseLine /> Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <h1 className="profile-name">{profile.name}</h1>
                    <div className="profile-details">
                      <span className="profile-detail">
                        <RiMailLine /> {profile.email}
                      </span>
                      <span className="profile-detail">
                        <RiMapPinLine /> {profile.location}
                      </span>
                      <span className="profile-detail">
                        <RiCalendarLine /> Member since {profile.memberSince}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {!editingProfile && (
              <AnimatedButton onClick={handleEditProfile}>
                <RiEditLine /> Edit Profile
              </AnimatedButton>
            )}
          </div>

          <div className="profile-stats">
            <div className="stat-item">
              <span className="stat-value">121</span>
              <span className="stat-label">Wardrobe Items</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">34</span>
              <span className="stat-label">Saved Outfits</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">18</span>
              <span className="stat-label">Purchases</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">4.8</span>
              <span className="stat-label">Style Score</span>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      <div className="profile-grid">
        {/* Measurements Section */}
        <motion.div className="measurements-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiRulerLine className="section-icon" />
                Measurements
              </h2>
              {editingMeasurements ? (
                <div className="section-actions">
                  <button className="icon-action save" onClick={handleSaveMeasurements}>
                    <RiCheckLine />
                  </button>
                  <button
                    className="icon-action cancel"
                    onClick={handleCancelMeasurementsEdit}
                  >
                    <RiCloseLine />
                  </button>
                </div>
              ) : (
                <button className="icon-action edit" onClick={handleEditMeasurements}>
                  <RiEditLine />
                </button>
              )}
            </div>

            <div className="measurements-grid">
              {(editingMeasurements ? tempMeasurements : measurements).map(
                (measurement, index) => {
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
                      <span className="measurement-label">
                        {measurement.label}
                      </span>
                      {editingMeasurements ? (
                        <input
                          type="text"
                          value={
                            tempMeasurements.find((m) => m.id === measurement.id)
                              ?.value || ''
                          }
                          onChange={(e) =>
                            updateMeasurement(measurement.id, e.target.value)
                          }
                          className="measurement-input"
                        />
                      ) : (
                        <span className="measurement-value">
                          {measurement.value}
                        </span>
                      )}
                      <span className="measurement-unit">
                        {measurement.unit}
                      </span>
                    </motion.div>
                  );
                }
              )}
            </div>
          </GlassCard>
        </motion.div>

        {/* Style Preferences */}
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
                  className={`style-tag ${
                    selectedTags.includes(tag) ? 'tag-active' : ''
                  }`}
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

        {/* Purchase History */}
        <motion.div className="history-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiHistoryLine className="section-icon" />
                Purchase History
              </h2>
              <span className="section-count">{purchaseHistory.length} orders</span>
            </div>

            <div className="purchase-list">
              {purchaseHistory.map((purchase, index) => (
                <motion.div
                  key={purchase.id}
                  className="purchase-item"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.08 }}
                >
                  <div className="purchase-icon">
                    <RiShoppingBag3Line />
                  </div>
                  <div className="purchase-details">
                    <span className="purchase-name">{purchase.name}</span>
                    <span className="purchase-brand">{purchase.brand}</span>
                  </div>
                  <div className="purchase-meta">
                    <span className="purchase-price">
                      ${purchase.price.toFixed(2)}
                    </span>
                    <span className="purchase-date">
                      {new Date(purchase.date).toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric',
                      })}
                    </span>
                    <span
                      className={`purchase-status ${getStatusColor(
                        purchase.status
                      )}`}
                    >
                      {purchase.status}
                    </span>
                  </div>
                </motion.div>
              ))}
            </div>
          </GlassCard>
        </motion.div>

        {/* Saved Outfits */}
        <motion.div className="outfits-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiGridLine className="section-icon" />
                Saved Outfits
              </h2>
              <button className="icon-action add">
                <RiAddLine />
              </button>
            </div>

            <div className="outfits-grid">
              {savedOutfits.map((outfit, index) => (
                <motion.div
                  key={outfit.id}
                  className="outfit-card"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: index * 0.08 }}
                  whileHover={{ scale: 1.03 }}
                >
                  <div className="outfit-image">
                    <RiImageLine className="outfit-image-icon" />
                    {outfit.favorite && (
                      <span className="outfit-favorite">
                        <RiHeartLine />
                      </span>
                    )}
                  </div>
                  <div className="outfit-info">
                    <span className="outfit-name">{outfit.name}</span>
                    <div className="outfit-meta">
                      <span>
                        <RiShirtLine /> {outfit.items} items
                      </span>
                      <span>
                        <RiCalendarLine /> {outfit.season}
                      </span>
                    </div>
                  </div>
                  <div className="outfit-actions">
                    <button className="outfit-action-btn" aria-label="View outfit">
                      <RiImageLine />
                    </button>
                    <button className="outfit-action-btn" aria-label="Delete outfit">
                      <RiDeleteBinLine />
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default Profile;
