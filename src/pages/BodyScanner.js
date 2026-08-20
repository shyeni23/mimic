import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiCamera3Line, RiBodyScanLine, RiPulseLine,
  RiCheckboxCircleLine, RiRestartLine, RiFullscreenLine,
  RiFlashlightLine, RiShapeLine, RiUserLine,
  RiRulerLine, RiPaletteLine, RiSparklingLine,
  RiErrorWarningLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import { useSession } from '../context/SessionContext';
import { apiPost } from '../utils/api';
import { mapBodyShape, mapFaceShape, mapSkinDepth, mapUndertone } from '../utils/mapBackendValues';
import './BodyScanner.css';

const detectionStages = [
  { key: 'posture', label: 'Posture Detection', icon: <RiUserLine /> },
  { key: 'body', label: 'Body Proportions', icon: <RiRulerLine /> },
  { key: 'shape', label: 'Body Shape Analysis', icon: <RiShapeLine /> },
  { key: 'skin', label: 'Skin Tone Analysis', icon: <RiPaletteLine /> },
  { key: 'face', label: 'Face Shape Detection', icon: <RiBodyScanLine /> },
];

function buildAnalysisFeatures(scan) {
  if (!scan) return [];
  return [
    { label: 'Body Shape', value: mapBodyShape(scan.body_shape), confidence: Math.round(scan.body_shape_confidence * 100) },
    { label: 'Face Shape', value: mapFaceShape(scan.face_shape), confidence: Math.round(scan.face_shape_confidence * 100) },
    { label: 'Skin Tone', value: scan.skin_tone_hex || '—', confidence: 60 },
    { label: 'Depth', value: mapSkinDepth(scan.skin_tone_depth), confidence: 60 },
    { label: 'Undertone', value: mapUndertone(scan.skin_tone_undertone), confidence: 60 },
    { label: 'Size Estimate', value: scan.size_estimate || '—', confidence: 40 },
  ];
}

export default function BodyScanner() {
  const navigate = useNavigate();
  const { sessionId, setScanData, fireAgentEvent } = useSession();

  const [scanState, setScanState] = useState('idle');
  const [scanProgress, setScanProgress] = useState(0);
  const [currentStage, setCurrentStage] = useState(0);
  const [detectedFeatures, setDetectedFeatures] = useState([]);
  const [scanLinePosition, setScanLinePosition] = useState(0);
  const [scanError, setScanError] = useState(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState(null);

  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const canvasRef = useRef(document.createElement('canvas'));
  const scanResultRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => setCameraReady(true);
        }
      })
      .catch((err) => {
        console.error('[body-scanner] Could not access camera:', err);
        if (!cancelled) {
          setCameraReady(false);
          setCameraError(err.message || err.name || 'camera access failed');
        }
      });
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !video.videoWidth) return null;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9));
  }, []);

  const startScan = useCallback(async () => {
    setScanState('scanning');
    setScanProgress(0);
    setCurrentStage(0);
    setDetectedFeatures([]);
    setScanLinePosition(0);
    setScanError(null);
    scanResultRef.current = null;

    const blob = await captureFrame();
    if (!blob || !sessionId) {
      setScanError(blob ? 'No session — please refresh.' : 'Could not capture frame from camera.');
      setScanState('error');
      return;
    }

    const form = new FormData();
    form.append('session_id', sessionId);
    form.append('frame', blob, 'frame.jpg');

    try {
      const res = await apiPost('/api/vision/scan', form, true);
      const data = await res.json();
      scanResultRef.current = data;
      setScanData(data);
    } catch (err) {
      setScanError(err.message || 'Scan failed');
      setScanState('error');
    }
  }, [captureFrame, sessionId, setScanData]);

  const resetScan = useCallback(() => {
    setScanState('idle');
    setScanProgress(0);
    setCurrentStage(0);
    setDetectedFeatures([]);
    setScanLinePosition(0);
    setScanError(null);
    scanResultRef.current = null;
  }, []);

  useEffect(() => {
    if (scanState !== 'scanning') return;

    const progressInterval = setInterval(() => {
      setScanProgress((prev) => {
        if (prev >= 100) {
          clearInterval(progressInterval);
          if (scanResultRef.current) {
            setScanState('complete');
            setDetectedFeatures(buildAnalysisFeatures(scanResultRef.current));
          }
          return 100;
        }
        if (prev >= 90 && !scanResultRef.current) return prev;
        return prev + 0.5;
      });
    }, 50);

    return () => clearInterval(progressInterval);
  }, [scanState]);

  // Proactive agent event: let Aria react the moment a scan finishes, even
  // if the customer hasn't said anything to her yet.
  useEffect(() => {
    if (scanState === 'complete') {
      fireAgentEvent('scan_complete');
    }
  }, [scanState, fireAgentEvent]);

  useEffect(() => {
    if (scanState !== 'scanning') return;

    const scanLineInterval = setInterval(() => {
      setScanLinePosition((prev) => (prev >= 100 ? 0 : prev + 0.8));
    }, 30);

    return () => clearInterval(scanLineInterval);
  }, [scanState]);

  useEffect(() => {
    if (scanState !== 'scanning') return;

    const stageIndex = Math.floor((scanProgress / 100) * detectionStages.length);
    if (stageIndex !== currentStage && stageIndex < detectionStages.length) {
      setCurrentStage(stageIndex);
    }

    const features = buildAnalysisFeatures(scanResultRef.current);
    if (features.length > 0) {
      const featureIndex = Math.floor((scanProgress / 100) * features.length);
      if (featureIndex > detectedFeatures.length && featureIndex <= features.length) {
        setDetectedFeatures(features.slice(0, featureIndex));
      }
    }
  }, [scanProgress, scanState, currentStage, detectedFeatures.length]);

  const finalFeatures = scanResultRef.current
    ? buildAnalysisFeatures(scanResultRef.current)
    : detectedFeatures;

  return (
    <div className="body-scanner">
      <motion.div
        className="scanner-header"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1>
            <RiBodyScanLine className="header-icon" />
            AI Body Scanner
          </h1>
          <p>Stand in front of the mirror for a full body analysis</p>
        </div>
        {(scanState === 'complete' || scanState === 'error') && (
          <AnimatedButton variant="ghost" size="small" onClick={resetScan}>
            <RiRestartLine /> New Scan
          </AnimatedButton>
        )}
      </motion.div>

      <div className="scanner-layout">
        <div className="scanner-main">
          <GlassCard className="scanner-viewport" hover={false} glow={scanState === 'scanning'}>
            <div className="viewport-inner">
              <div className="camera-feed">
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    transform: 'scaleX(-1)',
                    zIndex: 0,
                    borderRadius: 'inherit',
                  }}
                />

                {!cameraReady && scanState === 'idle' && (
                  <motion.div
                    className="camera-placeholder"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                  >
                    <div className="camera-icon-wrapper">
                      <RiCamera3Line />
                    </div>
                    <p>Position yourself within the frame</p>
                    <span>Ensure good lighting for best results</span>
                  </motion.div>
                )}

                {cameraReady && scanState === 'idle' && (
                  <motion.div
                    className="framing-hint"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    style={{
                      position: 'absolute',
                      bottom: 12,
                      left: 12,
                      right: 12,
                      padding: '10px 14px',
                      borderRadius: 12,
                      background: 'rgba(0, 0, 0, 0.55)',
                      backdropFilter: 'blur(8px)',
                      color: '#fff',
                      fontSize: '0.8rem',
                      textAlign: 'center',
                      zIndex: 2,
                    }}
                  >
                    Stand back until your <strong>shoulders and hips</strong> are both clearly visible --
                    that's what matters most for accuracy. Full head-to-feet framing gives a more
                    precise size estimate, but isn't required.
                  </motion.div>
                )}

                <div className="body-silhouette">
                  <svg viewBox="0 0 200 500" className="silhouette-svg">
                    <motion.path
                      d="M100,30 C115,30 125,45 125,60 C125,75 115,85 100,85 C85,85 75,75 75,60 C75,45 85,30 100,30 Z
                         M100,85 L100,95 M70,130 L100,110 L130,130
                         M100,95 C85,95 65,105 60,130 L60,135 L65,135 L70,130 L80,120
                         M100,95 C115,95 135,105 140,130 L140,135 L135,135 L130,130 L120,120
                         M100,110 L100,250 M100,250 L70,400 L65,470 L75,470 L85,400
                         M100,250 L130,400 L135,470 L125,470 L115,400"
                      fill="none"
                      stroke="rgba(108, 99, 255, 0.3)"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      initial={{ pathLength: 0, opacity: 0 }}
                      animate={
                        scanState !== 'idle'
                          ? { pathLength: 1, opacity: 1, stroke: 'rgba(108, 99, 255, 0.6)' }
                          : { pathLength: 0, opacity: 0 }
                      }
                      transition={{ duration: 3, ease: 'easeInOut' }}
                    />
                    {scanState === 'scanning' && (
                      <>
                        <motion.circle
                          cx="100" cy="60" r="22"
                          fill="none"
                          stroke="var(--secondary)"
                          strokeWidth="1"
                          strokeDasharray="4 4"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: [0.3, 0.8, 0.3], rotate: 360 }}
                          transition={{ duration: 3, repeat: Infinity }}
                        />
                        <motion.rect
                          x="55" y="95" width="90" height="160"
                          rx="8"
                          fill="none"
                          stroke="var(--primary)"
                          strokeWidth="1"
                          strokeDasharray="6 4"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: [0.2, 0.6, 0.2] }}
                          transition={{ duration: 2, repeat: Infinity, delay: 0.5 }}
                        />
                        <motion.rect
                          x="60" y="250" width="80" height="220"
                          rx="4"
                          fill="none"
                          stroke="var(--accent)"
                          strokeWidth="1"
                          strokeDasharray="6 4"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: [0.2, 0.5, 0.2] }}
                          transition={{ duration: 2.5, repeat: Infinity, delay: 1 }}
                        />
                      </>
                    )}
                    {scanState === 'complete' && (
                      <>
                        <motion.circle
                          cx="72" cy="130" r="4"
                          fill="var(--primary)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.1 }}
                        />
                        <motion.circle
                          cx="128" cy="130" r="4"
                          fill="var(--primary)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.2 }}
                        />
                        <motion.circle
                          cx="100" cy="170" r="4"
                          fill="var(--secondary)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.3 }}
                        />
                        <motion.circle
                          cx="100" cy="250" r="4"
                          fill="var(--secondary)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.4 }}
                        />
                        <motion.circle
                          cx="70" cy="400" r="4"
                          fill="var(--accent)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.5 }}
                        />
                        <motion.circle
                          cx="130" cy="400" r="4"
                          fill="var(--accent)"
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: 0.6 }}
                        />
                      </>
                    )}
                  </svg>
                </div>

                <AnimatePresence>
                  {scanState === 'scanning' && (
                    <motion.div
                      className="scan-overlay"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                    >
                      <motion.div
                        className="scan-line"
                        style={{ top: `${scanLinePosition}%` }}
                      />
                      <div className="scan-corners">
                        <span className="corner tl" />
                        <span className="corner tr" />
                        <span className="corner bl" />
                        <span className="corner br" />
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {scanState === 'complete' && (
                  <motion.div
                    className="scan-complete-badge"
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', stiffness: 200, damping: 15 }}
                  >
                    <RiCheckboxCircleLine />
                    <span>Scan Complete</span>
                  </motion.div>
                )}

                {scanState === 'error' && (
                  <motion.div
                    className="scan-complete-badge"
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    style={{ background: 'rgba(239, 68, 68, 0.2)', borderColor: 'rgba(239, 68, 68, 0.4)' }}
                  >
                    <RiErrorWarningLine />
                    <span>{scanError}</span>
                  </motion.div>
                )}
              </div>

              <div className="viewport-controls">
                <motion.button
                  className="viewport-btn"
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  title="Toggle Flash"
                >
                  <RiFlashlightLine />
                </motion.button>
                <motion.button
                  className="viewport-btn"
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  title="Fullscreen"
                >
                  <RiFullscreenLine />
                </motion.button>
              </div>
            </div>

            {scanState === 'scanning' && (
              <div className="scan-progress-bar">
                <motion.div
                  className="scan-progress-fill"
                  initial={{ width: 0 }}
                  animate={{ width: `${scanProgress}%` }}
                  transition={{ duration: 0.1 }}
                />
                <span className="scan-progress-text">{Math.round(scanProgress)}%</span>
              </div>
            )}
          </GlassCard>

          {scanState === 'idle' && (
            <motion.div
              className="scanner-cta"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <AnimatedButton
                onClick={startScan}
                icon={<RiBodyScanLine />}
                disabled={!cameraReady || !sessionId}
              >
                {cameraReady ? 'Start Body Scan' : cameraError ? 'Camera Unavailable' : 'Waiting for Camera...'}
              </AnimatedButton>
              <p className="scanner-hint" style={cameraError ? { color: 'var(--error, #ef4444)' } : undefined}>
                {cameraReady
                  ? 'Stand still and ensure good lighting for best results'
                  : cameraError
                  ? `Camera error: ${cameraError}. Check your browser's camera permission for this site, and make sure no other app/tab is using the camera.`
                  : 'Please allow camera access to continue'}
              </p>
            </motion.div>
          )}
        </div>

        <div className="scanner-sidebar">
          <GlassCard className="scanner-stages-card" delay={0.2}>
            <h3 className="sidebar-title">
              <RiPulseLine /> Detection Pipeline
            </h3>
            <div className="stage-list">
              {detectionStages.map((stage, i) => {
                let status = 'pending';
                if (scanState === 'complete') status = 'done';
                else if (scanState === 'scanning') {
                  if (i < currentStage) status = 'done';
                  else if (i === currentStage) status = 'active';
                }

                return (
                  <motion.div
                    key={stage.key}
                    className={`stage-item ${status}`}
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 + i * 0.08 }}
                  >
                    <div className={`stage-indicator ${status}`}>
                      {status === 'done' ? <RiCheckboxCircleLine /> : stage.icon}
                    </div>
                    <div className="stage-info">
                      <span className="stage-label">{stage.label}</span>
                      <span className="stage-status">
                        {status === 'done' && 'Complete'}
                        {status === 'active' && 'Analyzing...'}
                        {status === 'pending' && 'Pending'}
                      </span>
                    </div>
                    {status === 'active' && (
                      <motion.div
                        className="stage-pulse"
                        animate={{ scale: [1, 1.4, 1], opacity: [0.5, 0, 0.5] }}
                        transition={{ duration: 1.5, repeat: Infinity }}
                      />
                    )}
                  </motion.div>
                );
              })}
            </div>
          </GlassCard>

          <GlassCard className="scanner-analysis-card" delay={0.3}>
            <h3 className="sidebar-title">
              <RiSparklingLine /> Live Analysis
            </h3>
            <div className="analysis-list">
              <AnimatePresence>
                {detectedFeatures.length === 0 && scanState !== 'complete' && (
                  <motion.p
                    className="analysis-empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    {scanState === 'idle'
                      ? 'Start a scan to see live results'
                      : 'Detecting features...'}
                  </motion.p>
                )}
                {(scanState === 'complete' ? finalFeatures : detectedFeatures).map(
                  (feature, i) => (
                    <motion.div
                      key={feature.label}
                      className="analysis-row"
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                    >
                      <div className="analysis-label">{feature.label}</div>
                      <div className="analysis-value">{feature.value}</div>
                      <div className="analysis-confidence">
                        <div className="confidence-bar">
                          <motion.div
                            className="confidence-fill"
                            initial={{ width: 0 }}
                            animate={{ width: `${feature.confidence}%` }}
                            transition={{ duration: 0.8, delay: i * 0.1 }}
                          />
                        </div>
                        <span>{feature.confidence}%</span>
                      </div>
                    </motion.div>
                  )
                )}
              </AnimatePresence>
            </div>
          </GlassCard>

          {scanState === 'complete' && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
            >
              <AnimatedButton
                fullWidth
                variant="primary"
                onClick={() => navigate('/analysis-results')}
                icon={<RiSparklingLine />}
              >
                View Full Analysis
              </AnimatedButton>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
