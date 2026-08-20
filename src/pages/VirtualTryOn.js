import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiCameraLine,
  RiCameraSwitchLine,
  RiSunLine,
  RiFlashlightLine,
  RiMoonLine,
  RiContrastLine,
  RiZoomInLine,
  RiCloseLine,
  RiImageLine,
  RiRefreshLine,
  RiTShirtLine,
  RiFootprintLine,
  RiHandbagLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import './VirtualTryOn.css';

const LIGHTING_MODES = [
  { id: 'natural', label: 'Natural', icon: <RiSunLine /> },
  { id: 'studio', label: 'Studio', icon: <RiFlashlightLine /> },
  { id: 'warm', label: 'Warm', icon: <RiContrastLine /> },
  { id: 'cool', label: 'Cool', icon: <RiMoonLine /> },
];

const CURRENT_OUTFIT_ITEMS = [
  { id: 'o1', name: 'Silk Blouse', category: 'Top', emoji: '👔', icon: <RiTShirtLine /> },
  { id: 'o2', name: 'Slim Jeans', category: 'Bottom', emoji: '👖', icon: <RiTShirtLine /> },
  { id: 'o3', name: 'White Sneakers', category: 'Shoes', emoji: '👟', icon: <RiFootprintLine /> },
  { id: 'o4', name: 'Crossbody Bag', category: 'Bag', emoji: '👝', icon: <RiHandbagLine /> },
];

export default function VirtualTryOn() {
  const [lightingMode, setLightingMode] = useState('natural');
  const [zoom, setZoom] = useState(1);
  const [capturedPhoto, setCapturedPhoto] = useState(null);
  const [isFlipped, setIsFlipped] = useState(false);
  const [showFlash, setShowFlash] = useState(false);

  const handleCapture = () => {
    setShowFlash(true);
    setTimeout(() => {
      setShowFlash(false);
      setCapturedPhoto({
        timestamp: new Date().toLocaleTimeString(),
        lighting: lightingMode,
      });
    }, 300);
  };

  const handleDismissCapture = () => {
    setCapturedPhoto(null);
  };

  const handleFlipCamera = () => {
    setIsFlipped((prev) => !prev);
  };

  const getLightingOverlay = () => {
    switch (lightingMode) {
      case 'studio':
        return 'rgba(255, 255, 255, 0.04)';
      case 'warm':
        return 'rgba(255, 180, 80, 0.06)';
      case 'cool':
        return 'rgba(100, 180, 255, 0.06)';
      default:
        return 'transparent';
    }
  };

  return (
    <motion.div
      className="virtual-tryon-page"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="tryon-layout">
        {/* Main Mirror Area */}
        <div className="mirror-section">
          <div className="mirror-container">
            {/* Mirror Frame */}
            <motion.div
              className="mirror-frame"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
            >
              {/* Camera Preview */}
              <div
                className="camera-preview"
                style={{
                  transform: `scale(${zoom})${isFlipped ? ' scaleX(-1)' : ''}`,
                  backgroundColor: getLightingOverlay(),
                }}
              >
                {/* Lighting Overlay */}
                <div
                  className="lighting-overlay"
                  style={{ background: getLightingOverlay() }}
                />

                {/* Placeholder Content */}
                <div className="camera-placeholder">
                  <motion.div
                    className="camera-icon-wrapper"
                    animate={{
                      scale: [1, 1.05, 1],
                      opacity: [0.4, 0.6, 0.4],
                    }}
                    transition={{
                      duration: 3,
                      repeat: Infinity,
                      ease: 'easeInOut',
                    }}
                  >
                    <RiCameraLine className="camera-icon" />
                  </motion.div>
                  <p className="camera-text">
                    Position yourself in front of the mirror
                  </p>
                  <p className="camera-subtext">
                    Camera feed will appear here
                  </p>
                </div>

                {/* AR Outfit Overlay */}
                <div className="ar-overlay">
                  <div className="ar-silhouette">
                    <motion.div
                      className="ar-silhouette-body"
                      animate={{ opacity: [0.15, 0.25, 0.15] }}
                      transition={{
                        duration: 4,
                        repeat: Infinity,
                        ease: 'easeInOut',
                      }}
                    >
                      <div className="silhouette-head" />
                      <div className="silhouette-torso" />
                      <div className="silhouette-legs" />
                    </motion.div>
                  </div>
                </div>

                {/* Zoom Indicator */}
                {zoom !== 1 && (
                  <motion.div
                    className="zoom-indicator"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                  >
                    <RiZoomInLine /> {zoom.toFixed(1)}x
                  </motion.div>
                )}

                {/* Lighting Badge */}
                <div className="lighting-badge">
                  {LIGHTING_MODES.find((m) => m.id === lightingMode)?.icon}
                  <span>{LIGHTING_MODES.find((m) => m.id === lightingMode)?.label}</span>
                </div>

                {/* Flash Effect */}
                <AnimatePresence>
                  {showFlash && (
                    <motion.div
                      className="flash-overlay"
                      initial={{ opacity: 1 }}
                      animate={{ opacity: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.3 }}
                    />
                  )}
                </AnimatePresence>
              </div>
            </motion.div>

            {/* Captured Photo Preview */}
            <AnimatePresence>
              {capturedPhoto && (
                <motion.div
                  className="captured-preview"
                  initial={{ opacity: 0, scale: 0.8, y: 20 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.8, y: 20 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                >
                  <GlassCard className="captured-card" hover={false}>
                    <div className="captured-content">
                      <div className="captured-image-placeholder">
                        <RiImageLine />
                        <span>Photo Captured</span>
                      </div>
                      <div className="captured-info">
                        <span className="captured-time">
                          {capturedPhoto.timestamp}
                        </span>
                        <span className="captured-lighting">
                          {capturedPhoto.lighting} lighting
                        </span>
                      </div>
                      <motion.button
                        className="captured-dismiss"
                        onClick={handleDismissCapture}
                        whileHover={{ scale: 1.1 }}
                        whileTap={{ scale: 0.9 }}
                      >
                        <RiCloseLine />
                      </motion.button>
                    </div>
                  </GlassCard>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Control Bar */}
            <motion.div
              className="controls-bar"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.3 }}
            >
              <GlassCard className="controls-card" hover={false}>
                <div className="controls-layout">
                  {/* Lighting Mode Selector */}
                  <div className="controls-group lighting-controls">
                    <span className="controls-group-label">Lighting</span>
                    <div className="lighting-buttons">
                      {LIGHTING_MODES.map((mode) => (
                        <motion.button
                          key={mode.id}
                          className={`lighting-btn ${lightingMode === mode.id ? 'active' : ''}`}
                          onClick={() => setLightingMode(mode.id)}
                          whileHover={{ scale: 1.1 }}
                          whileTap={{ scale: 0.9 }}
                          title={mode.label}
                        >
                          {mode.icon}
                        </motion.button>
                      ))}
                    </div>
                  </div>

                  {/* Zoom Slider */}
                  <div className="controls-group zoom-controls">
                    <span className="controls-group-label">
                      Zoom {zoom.toFixed(1)}x
                    </span>
                    <div className="zoom-slider-wrapper">
                      <input
                        type="range"
                        min="0.5"
                        max="3"
                        step="0.1"
                        value={zoom}
                        onChange={(e) => setZoom(parseFloat(e.target.value))}
                        className="zoom-slider"
                      />
                    </div>
                  </div>

                  {/* Capture & Flip Buttons */}
                  <div className="controls-group action-controls">
                    <motion.button
                      className="flip-btn"
                      onClick={handleFlipCamera}
                      whileHover={{ scale: 1.1, rotate: 180 }}
                      whileTap={{ scale: 0.9 }}
                      title="Flip Camera"
                    >
                      <RiCameraSwitchLine />
                    </motion.button>

                    <motion.button
                      className="capture-btn"
                      onClick={handleCapture}
                      whileHover={{ scale: 1.08 }}
                      whileTap={{ scale: 0.92 }}
                      title="Capture Photo"
                    >
                      <span className="capture-btn-inner">
                        <RiCameraLine />
                      </span>
                    </motion.button>

                    <div className="flip-btn-spacer" />
                  </div>
                </div>
              </GlassCard>
            </motion.div>
          </div>
        </div>

        {/* Side Panel - Outfit Items */}
        <motion.div
          className="tryon-side-panel"
          initial={{ opacity: 0, x: 30 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <GlassCard className="side-panel-card" hover={false}>
            <h3 className="side-panel-title">Current Outfit</h3>
            <p className="side-panel-subtitle">Items being tried on</p>

            <div className="tryon-items-list">
              {CURRENT_OUTFIT_ITEMS.map((item, index) => (
                <motion.div
                  key={item.id}
                  className="tryon-item"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, delay: 0.4 + index * 0.1 }}
                  whileHover={{ x: 4 }}
                >
                  <span className="tryon-item-emoji">{item.emoji}</span>
                  <div className="tryon-item-info">
                    <span className="tryon-item-name">{item.name}</span>
                    <span className="tryon-item-category">{item.category}</span>
                  </div>
                  <span className="tryon-item-icon">{item.icon}</span>
                </motion.div>
              ))}
            </div>

            <div className="side-panel-actions">
              <AnimatedButton
                variant="primary"
                fullWidth
                icon={<RiRefreshLine />}
              >
                Try Another Outfit
              </AnimatedButton>
            </div>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  );
}
