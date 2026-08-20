import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  RiSettings4Line,
  RiSunLine,
  RiMoonLine,
  RiNotification3Line,
  RiMailLine,
  RiSmartphoneLine,
  RiVolumeUpLine,
  RiGlobalLine,
  RiTranslate2,
  RiShieldLine,
  RiEyeLine,
  RiEyeOffLine,
  RiMapPinLine,
  RiLockLine,
  RiKeyLine,
  RiDeleteBinLine,
  RiUserLine,
  RiLogoutBoxLine,
  RiInformationLine,
  RiCodeLine,
  RiHeartLine,
  RiExternalLinkLine,
  RiQuestionLine,
  RiFileTextLine,
  RiCheckLine,
  RiArrowRightSLine,
  RiFingerprintLine,
  RiDatabase2Line,
  RiWifiLine,
} from 'react-icons/ri';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import './Settings.css';

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

const languages = [
  { code: 'en', name: 'English', flag: 'EN' },
  { code: 'es', name: 'Spanish', flag: 'ES' },
  { code: 'fr', name: 'French', flag: 'FR' },
  { code: 'de', name: 'German', flag: 'DE' },
  { code: 'it', name: 'Italian', flag: 'IT' },
  { code: 'pt', name: 'Portuguese', flag: 'PT' },
  { code: 'ja', name: 'Japanese', flag: 'JA' },
  { code: 'ko', name: 'Korean', flag: 'KO' },
  { code: 'zh', name: 'Chinese', flag: 'ZH' },
];

const ToggleSwitch = ({ enabled, onToggle, id }) => (
  <button
    className={`toggle-switch ${enabled ? 'toggle-on' : 'toggle-off'}`}
    onClick={onToggle}
    role="switch"
    aria-checked={enabled}
    id={id}
  >
    <motion.div
      className="toggle-thumb"
      layout
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
    />
  </button>
);

const Settings = () => {
  const { theme, toggleTheme } = useTheme();
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleAdminLogout = () => {
    logout();
    navigate('/');
  };

  const [notifications, setNotifications] = useState({
    email: true,
    push: true,
    sound: false,
    outfitReminders: true,
    weatherAlerts: true,
    promotions: false,
    weeklyDigest: true,
  });

  const [language, setLanguage] = useState('en');
  const [languageDropdownOpen, setLanguageDropdownOpen] = useState(false);

  const [privacy, setPrivacy] = useState({
    profileVisible: true,
    shareAnalytics: false,
    locationTracking: true,
    biometricLock: false,
    dataSync: true,
  });

  const toggleNotification = (key) => {
    setNotifications((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const togglePrivacy = (key) => {
    setPrivacy((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const selectedLanguage = languages.find((l) => l.code === language);

  return (
    <motion.div
      className="settings-page"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div className="settings-header" variants={itemVariants}>
        <h1 className="page-title">
          <RiSettings4Line className="title-icon" />
          Settings
        </h1>
        <p className="page-subtitle">
          Customize your Smart Mirror experience
        </p>
      </motion.div>

      <div className="settings-grid">
        {/* Theme Toggle */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                {theme === 'dark' ? (
                  <RiMoonLine className="section-icon" />
                ) : (
                  <RiSunLine className="section-icon" />
                )}
                Appearance
              </h2>
            </div>

            <div className="setting-item">
              <div className="setting-info">
                <div className="setting-icon-wrap">
                  {theme === 'dark' ? <RiMoonLine /> : <RiSunLine />}
                </div>
                <div>
                  <span className="setting-label">Theme</span>
                  <span className="setting-description">
                    {theme === 'dark' ? 'Dark mode' : 'Light mode'} is active
                  </span>
                </div>
              </div>
              <div className="theme-toggle-container">
                <span className="theme-label">
                  <RiSunLine />
                </span>
                <ToggleSwitch
                  enabled={theme === 'dark'}
                  onToggle={toggleTheme}
                  id="theme-toggle"
                />
                <span className="theme-label">
                  <RiMoonLine />
                </span>
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Notification Preferences */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiNotification3Line className="section-icon" />
                Notifications
              </h2>
            </div>

            <div className="settings-list">
              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiMailLine />
                  </div>
                  <div>
                    <span className="setting-label">Email Notifications</span>
                    <span className="setting-description">
                      Receive updates via email
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.email}
                  onToggle={() => toggleNotification('email')}
                  id="email-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiSmartphoneLine />
                  </div>
                  <div>
                    <span className="setting-label">Push Notifications</span>
                    <span className="setting-description">
                      Mobile push alerts
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.push}
                  onToggle={() => toggleNotification('push')}
                  id="push-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiVolumeUpLine />
                  </div>
                  <div>
                    <span className="setting-label">Sound Alerts</span>
                    <span className="setting-description">
                      Play sounds for notifications
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.sound}
                  onToggle={() => toggleNotification('sound')}
                  id="sound-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiNotification3Line />
                  </div>
                  <div>
                    <span className="setting-label">Outfit Reminders</span>
                    <span className="setting-description">
                      Daily outfit suggestions
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.outfitReminders}
                  onToggle={() => toggleNotification('outfitReminders')}
                  id="outfit-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiGlobalLine />
                  </div>
                  <div>
                    <span className="setting-label">Weather Alerts</span>
                    <span className="setting-description">
                      Get notified about weather changes
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.weatherAlerts}
                  onToggle={() => toggleNotification('weatherAlerts')}
                  id="weather-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiMailLine />
                  </div>
                  <div>
                    <span className="setting-label">Promotions</span>
                    <span className="setting-description">
                      Sales and promotional offers
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.promotions}
                  onToggle={() => toggleNotification('promotions')}
                  id="promo-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiFileTextLine />
                  </div>
                  <div>
                    <span className="setting-label">Weekly Digest</span>
                    <span className="setting-description">
                      Summary of your weekly style activity
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={notifications.weeklyDigest}
                  onToggle={() => toggleNotification('weeklyDigest')}
                  id="digest-toggle"
                />
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Language Selector */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiTranslate2 className="section-icon" />
                Language
              </h2>
            </div>

            <div className="setting-item language-setting">
              <div className="setting-info">
                <div className="setting-icon-wrap">
                  <RiGlobalLine />
                </div>
                <div>
                  <span className="setting-label">Display Language</span>
                  <span className="setting-description">
                    Choose your preferred language
                  </span>
                </div>
              </div>

              <div className="language-dropdown-container">
                <button
                  className="language-selector"
                  onClick={() => setLanguageDropdownOpen(!languageDropdownOpen)}
                >
                  <span className="lang-flag">{selectedLanguage?.flag}</span>
                  <span className="lang-name">{selectedLanguage?.name}</span>
                  <RiArrowRightSLine
                    className={`dropdown-arrow ${
                      languageDropdownOpen ? 'dropdown-open' : ''
                    }`}
                  />
                </button>

                {languageDropdownOpen && (
                  <motion.div
                    className="language-dropdown"
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                  >
                    {languages.map((lang) => (
                      <button
                        key={lang.code}
                        className={`language-option ${
                          language === lang.code ? 'lang-active' : ''
                        }`}
                        onClick={() => {
                          setLanguage(lang.code);
                          setLanguageDropdownOpen(false);
                        }}
                      >
                        <span className="lang-flag">{lang.flag}</span>
                        <span className="lang-name">{lang.name}</span>
                        {language === lang.code && (
                          <RiCheckLine className="lang-check" />
                        )}
                      </button>
                    ))}
                  </motion.div>
                )}
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Privacy Settings */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiShieldLine className="section-icon" />
                Privacy & Security
              </h2>
            </div>

            <div className="settings-list">
              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    {privacy.profileVisible ? <RiEyeLine /> : <RiEyeOffLine />}
                  </div>
                  <div>
                    <span className="setting-label">Profile Visibility</span>
                    <span className="setting-description">
                      Make your profile visible to others
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={privacy.profileVisible}
                  onToggle={() => togglePrivacy('profileVisible')}
                  id="profile-visible-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiDatabase2Line />
                  </div>
                  <div>
                    <span className="setting-label">Share Analytics</span>
                    <span className="setting-description">
                      Help improve AI recommendations
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={privacy.shareAnalytics}
                  onToggle={() => togglePrivacy('shareAnalytics')}
                  id="analytics-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiMapPinLine />
                  </div>
                  <div>
                    <span className="setting-label">Location Services</span>
                    <span className="setting-description">
                      Enable weather-based suggestions
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={privacy.locationTracking}
                  onToggle={() => togglePrivacy('locationTracking')}
                  id="location-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiFingerprintLine />
                  </div>
                  <div>
                    <span className="setting-label">Biometric Lock</span>
                    <span className="setting-description">
                      Use fingerprint or face to unlock
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={privacy.biometricLock}
                  onToggle={() => togglePrivacy('biometricLock')}
                  id="biometric-toggle"
                />
              </div>

              <div className="setting-item">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiWifiLine />
                  </div>
                  <div>
                    <span className="setting-label">Data Sync</span>
                    <span className="setting-description">
                      Sync wardrobe data across devices
                    </span>
                  </div>
                </div>
                <ToggleSwitch
                  enabled={privacy.dataSync}
                  onToggle={() => togglePrivacy('dataSync')}
                  id="sync-toggle"
                />
              </div>
            </div>
          </GlassCard>
        </motion.div>

        {/* Account Section */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiUserLine className="section-icon" />
                Account
              </h2>
            </div>

            <div className="settings-list">
              <button className="setting-item setting-action">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiKeyLine />
                  </div>
                  <div>
                    <span className="setting-label">Change Password</span>
                    <span className="setting-description">
                      Update your account password
                    </span>
                  </div>
                </div>
                <RiArrowRightSLine className="action-arrow" />
              </button>

              <button className="setting-item setting-action">
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiLockLine />
                  </div>
                  <div>
                    <span className="setting-label">Two-Factor Authentication</span>
                    <span className="setting-description">
                      Add an extra layer of security
                    </span>
                  </div>
                </div>
                <RiArrowRightSLine className="action-arrow" />
              </button>

              <button className="setting-item setting-action" onClick={handleAdminLogout}>
                <div className="setting-info">
                  <div className="setting-icon-wrap">
                    <RiLogoutBoxLine />
                  </div>
                  <div>
                    <span className="setting-label">End Shift (Admin Logout)</span>
                    <span className="setting-description">
                      Lock the mirror and return to admin sign-in
                    </span>
                  </div>
                </div>
                <RiArrowRightSLine className="action-arrow" />
              </button>

              <button className="setting-item setting-action danger">
                <div className="setting-info">
                  <div className="setting-icon-wrap danger-icon">
                    <RiDeleteBinLine />
                  </div>
                  <div>
                    <span className="setting-label danger-text">
                      Delete Account
                    </span>
                    <span className="setting-description">
                      Permanently delete your account and data
                    </span>
                  </div>
                </div>
                <RiArrowRightSLine className="action-arrow" />
              </button>
            </div>
          </GlassCard>
        </motion.div>

        {/* About Section */}
        <motion.div className="settings-section" variants={itemVariants}>
          <GlassCard>
            <div className="section-header">
              <h2>
                <RiInformationLine className="section-icon" />
                About
              </h2>
            </div>

            <div className="about-content">
              <div className="about-logo">
                <div className="about-logo-icon">
                  <RiHeartLine />
                </div>
                <div className="about-app-info">
                  <h3>AI Smart Mirror</h3>
                  <span className="about-version">Version 2.1.0</span>
                </div>
              </div>

              <p className="about-description">
                Your intelligent personal stylist powered by AI. Get
                personalized outfit recommendations, wardrobe analysis, and
                shopping suggestions tailored to your unique style.
              </p>

              <div className="about-links">
                <button className="about-link">
                  <RiQuestionLine />
                  Help Center
                  <RiExternalLinkLine className="external-icon" />
                </button>
                <button className="about-link">
                  <RiFileTextLine />
                  Terms of Service
                  <RiExternalLinkLine className="external-icon" />
                </button>
                <button className="about-link">
                  <RiShieldLine />
                  Privacy Policy
                  <RiExternalLinkLine className="external-icon" />
                </button>
                <button className="about-link">
                  <RiCodeLine />
                  Open Source Licenses
                  <RiExternalLinkLine className="external-icon" />
                </button>
              </div>

              <div className="about-footer">
                <span>Made with care by the Smart Mirror Team</span>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  );
};

export default Settings;
