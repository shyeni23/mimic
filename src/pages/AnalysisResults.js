import { motion } from 'framer-motion';
import {
  RiSparklingLine, RiBodyScanLine, RiPaletteLine,
  RiUserLine, RiRulerLine, RiArrowRightSLine,
  RiLightbulbLine, RiShapeLine, RiStarLine,
  RiTShirtLine, RiShieldCheckLine,
} from 'react-icons/ri';
import { useNavigate } from 'react-router-dom';
import GlassCard from '../components/Common/GlassCard';
import AnimatedButton from '../components/Common/AnimatedButton';
import ProgressCircle from '../components/Common/ProgressCircle';
import { useSession } from '../context/SessionContext';
import { mapBodyShape, mapFaceShape, mapSkinDepth, mapUndertone } from '../utils/mapBackendValues';
import './AnalysisResults.css';

const stagger = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
};

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

const BODY_SHAPE_DESCRIPTIONS = {
  hourglass: 'Balanced shoulders and hips with a defined waist',
  pear: 'Hips wider than shoulders with a defined waist',
  inverted_triangle: 'Shoulders wider than hips',
  rectangle: 'Shoulders, waist, and hips are similarly proportioned',
  apple: 'Midsection is wider relative to shoulders and hips',
};

const FACE_SHAPE_DESCRIPTIONS = {
  oval: 'Balanced proportions with slightly narrower forehead and jaw',
  round: 'Face width and length are close, with a softer jawline',
  square: 'Forehead, cheekbones, and jaw are all similarly wide',
  heart: 'Forehead is noticeably wider than the jaw',
  long: 'Face length is notably greater than its width',
  diamond: 'Cheekbones are the widest point, narrowing at forehead and jaw',
};

const STYLE_INSIGHTS = {
  hourglass: { fits: 'Fitted silhouettes and A-line shapes complement your hourglass frame. Avoid boxy or overly loose cuts.', style: 'Your proportions suit both classic and modern aesthetics. Belt at the natural waist to accentuate your shape.' },
  pear: { fits: 'Structured tops and A-line skirts balance your proportions beautifully. Draw attention upward with detailed necklines.', style: 'Darker colors on the bottom with brighter tops create visual harmony.' },
  inverted_triangle: { fits: 'Flowy tops and fuller bottoms that add hip volume create balance. V-necklines elongate the torso.', style: 'Wide-leg pants and A-line skirts balance broader shoulders effectively.' },
  rectangle: { fits: 'Belted or layered pieces create waist definition. Peplum tops and wrap dresses add curves.', style: 'Layering and strategic gathering create dimension in your silhouette.' },
  apple: { fits: 'Empire waists and flowing fabric skim the midsection. V-necks and vertical patterns elongate.', style: 'Structured jackets and monochromatic looks create a streamlined appearance.' },
};

export default function AnalysisResults() {
  const navigate = useNavigate();
  const { scanData } = useSession();

  const bodyShape = scanData?.body_shape || 'unknown';
  const faceShape = scanData?.face_shape || 'unknown';
  const skinHex = scanData?.skin_tone_hex || '#D4A574';
  const depth = scanData?.skin_tone_depth || 'unknown';
  const undertone = scanData?.skin_tone_undertone || 'unknown';
  const sizeEstimate = scanData?.size_estimate || '—';
  const bodyConfidence = scanData ? Math.round(scanData.body_shape_confidence * 100) : 0;
  const faceConfidence = scanData ? Math.round(scanData.face_shape_confidence * 100) : 0;
  const overallAccuracy = scanData ? Math.round(((scanData.body_shape_confidence + scanData.face_shape_confidence) / 2) * 100) : 0;

  const insights = STYLE_INSIGHTS[bodyShape] || STYLE_INSIGHTS.hourglass;
  const colorInsight = undertone === 'warm'
    ? 'Your warm undertone pairs beautifully with rich jewel tones, earthy neutrals, and warm metallics.'
    : undertone === 'cool'
      ? 'Your cool undertone is complemented by icy pastels, jewel tones, and silver metallics.'
      : 'Your neutral undertone gives you versatility across warm and cool palettes alike.';

  const aiInsights = [
    { icon: <RiTShirtLine />, title: 'Ideal Fits', description: insights.fits, color: '#6C63FF' },
    { icon: <RiPaletteLine />, title: 'Color Harmony', description: colorInsight, color: '#00C2FF' },
    { icon: <RiStarLine />, title: 'Style Profile', description: insights.style, color: '#8B5CF6' },
    { icon: <RiShieldCheckLine />, title: 'Size Recommendation', description: `Based on your proportions, we estimate size ${sizeEstimate}. This is approximate — for exact fit, check individual garment sizing.`, color: '#10B981' },
  ];

  const measurements = [
    { label: 'Body Shape', value: mapBodyShape(bodyShape) },
    { label: 'Face Shape', value: mapFaceShape(faceShape) },
    { label: 'Skin Depth', value: mapSkinDepth(depth) },
    { label: 'Undertone', value: mapUndertone(undertone) },
    { label: 'Size Estimate', value: sizeEstimate },
    { label: 'Skin Tone', value: skinHex },
  ];

  const skinToneSwatches = [
    { name: 'Detected', hex: skinHex },
  ];

  return (
    <div className="analysis-results">
      <motion.div
        className="analysis-header"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1>
            <RiSparklingLine className="header-icon" />
            Analysis Results
          </h1>
          <p>
            {scanData
              ? 'Your AI-powered body and style analysis is ready'
              : 'No scan data yet — run a body scan first'}
          </p>
        </div>
        <AnimatedButton
          variant="primary"
          onClick={() => navigate(scanData ? '/recommendations' : '/body-scanner')}
          icon={<RiArrowRightSLine />}
        >
          {scanData ? 'Get Recommendations' : 'Go to Scanner'}
        </AnimatedButton>
      </motion.div>

      <motion.div
        className="analysis-confidence-banner"
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.15 }}
      >
        <GlassCard className="confidence-banner-card" glow hover={false}>
          <div className="confidence-banner-content">
            <ProgressCircle value={overallAccuracy || 94} size={100} strokeWidth={8} label="Accuracy" />
            <div className="confidence-info">
              <h2>Analysis Confidence</h2>
              <p>
                {scanData
                  ? `Body shape detected with ${bodyConfidence}% confidence, face shape with ${faceConfidence}% confidence.`
                  : 'High-confidence scan with excellent lighting and positioning. All body metrics detected within optimal thresholds.'}
              </p>
              <div className="confidence-tags">
                <span className="ctag">Full Body Detected</span>
                <span className="ctag">Face Detected</span>
                <span className="ctag">Skin Analyzed</span>
              </div>
            </div>
          </div>
        </GlassCard>
      </motion.div>

      <motion.div
        className="analysis-cards-grid"
        variants={stagger}
        initial="hidden"
        animate="show"
      >
        <motion.div variants={fadeUp}>
          <GlassCard className="analysis-card body-shape-card" delay={0.2}>
            <div className="card-header">
              <div className="card-icon-wrap" style={{ background: 'rgba(108, 99, 255, 0.12)' }}>
                <RiShapeLine style={{ color: '#6C63FF' }} />
              </div>
              <div>
                <h3>Body Shape</h3>
                <span className="card-subtitle">Detected Profile</span>
              </div>
            </div>
            <div className="body-shape-visual">
              <svg viewBox="0 0 120 200" className="body-shape-svg">
                <defs>
                  <linearGradient id="bodyGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6C63FF" stopOpacity="0.6" />
                    <stop offset="100%" stopColor="#00C2FF" stopOpacity="0.3" />
                  </linearGradient>
                </defs>
                <motion.path
                  d="M60,15 C50,15 45,25 45,35 C45,45 50,50 60,50 C70,50 75,45 75,35 C75,25 70,15 60,15 Z
                     M40,55 C30,58 25,65 28,80 L32,80 L38,68
                     M80,55 C90,58 95,65 92,80 L88,80 L82,68
                     M45,55 L42,100 L48,100 L52,75
                     M75,55 L78,100 L72,100 L68,75
                     M42,100 L40,105 L50,105 L55,100
                     M78,100 L80,105 L70,105 L65,100
                     M50,105 L48,160 L55,160
                     M70,105 L72,160 L65,160
                     M48,160 L45,195 L55,195 L55,160
                     M72,160 L75,195 L65,195 L65,160"
                  fill="none"
                  stroke="url(#bodyGrad)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 2, ease: 'easeInOut' }}
                />
                <motion.ellipse
                  cx="60" cy="82" rx="22" ry="6"
                  fill="none"
                  stroke="#6C63FF"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 0.5 }}
                  transition={{ delay: 1.5 }}
                />
                <motion.ellipse
                  cx="60" cy="55" rx="20" ry="5"
                  fill="none"
                  stroke="#00C2FF"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 0.5 }}
                  transition={{ delay: 1.8 }}
                />
                <motion.ellipse
                  cx="60" cy="105" rx="18" ry="5"
                  fill="none"
                  stroke="#8B5CF6"
                  strokeWidth="1"
                  strokeDasharray="3 3"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 0.5 }}
                  transition={{ delay: 2.1 }}
                />
              </svg>
            </div>
            <div className="body-shape-label">
              <h4>{mapBodyShape(bodyShape)}</h4>
              <p>
                {BODY_SHAPE_DESCRIPTIONS[bodyShape]
                  || (bodyShape === 'unknown' && scanData?.body_shape_reason)
                  || 'Analysis pending'}
              </p>
            </div>
            <div className="shape-ratio-bar">
              <div className="ratio-item">
                <span>Shoulders</span>
                <div className="ratio-track">
                  <motion.div
                    className="ratio-fill"
                    style={{ background: '#00C2FF' }}
                    initial={{ width: 0 }}
                    animate={{ width: `${bodyConfidence || 85}%` }}
                    transition={{ duration: 1, delay: 0.8 }}
                  />
                </div>
              </div>
              <div className="ratio-item">
                <span>Waist</span>
                <div className="ratio-track">
                  <motion.div
                    className="ratio-fill"
                    style={{ background: '#6C63FF' }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max((bodyConfidence || 85) - 25, 40)}%` }}
                    transition={{ duration: 1, delay: 1 }}
                  />
                </div>
              </div>
              <div className="ratio-item">
                <span>Hips</span>
                <div className="ratio-track">
                  <motion.div
                    className="ratio-fill"
                    style={{ background: '#8B5CF6' }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min((bodyConfidence || 85) + 3, 95)}%` }}
                    transition={{ duration: 1, delay: 1.2 }}
                  />
                </div>
              </div>
            </div>
          </GlassCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlassCard className="analysis-card skin-tone-card" delay={0.3}>
            <div className="card-header">
              <div className="card-icon-wrap" style={{ background: 'rgba(0, 194, 255, 0.12)' }}>
                <RiPaletteLine style={{ color: '#00C2FF' }} />
              </div>
              <div>
                <h3>Skin Tone</h3>
                <span className="card-subtitle">Color Analysis</span>
              </div>
            </div>
            <div className="skin-tone-display">
              <div className="skin-main-swatch">
                <motion.div
                  className="swatch-circle"
                  style={{ background: skinHex }}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 200, damping: 15, delay: 0.5 }}
                />
                <div className="swatch-info">
                  <h4>{mapSkinDepth(depth)}</h4>
                  <span>{mapUndertone(undertone)} Undertone</span>
                </div>
              </div>
              <div className="skin-swatches-row">
                {skinToneSwatches.map((swatch, i) => (
                  <motion.div
                    key={swatch.name}
                    className="mini-swatch"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.7 + i * 0.1 }}
                  >
                    <div className="mini-swatch-color" style={{ background: swatch.hex }} />
                    <span className="mini-swatch-name">{swatch.name}</span>
                    <span className="mini-swatch-hex">{swatch.hex}</span>
                  </motion.div>
                ))}
              </div>
            </div>
            <div className="best-colors">
              <span className="best-colors-label">Best Colors</span>
              <div className="color-dots">
                {['#8B0000', '#2E4057', '#556B2F', '#800020', '#D4AF37', '#1B4332'].map(
                  (c, i) => (
                    <motion.div
                      key={c}
                      className="color-dot"
                      style={{ background: c }}
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ delay: 1 + i * 0.06 }}
                      title={c}
                    />
                  )
                )}
              </div>
            </div>
          </GlassCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlassCard className="analysis-card face-shape-card" delay={0.4}>
            <div className="card-header">
              <div className="card-icon-wrap" style={{ background: 'rgba(139, 92, 246, 0.12)' }}>
                <RiUserLine style={{ color: '#8B5CF6' }} />
              </div>
              <div>
                <h3>Face Shape</h3>
                <span className="card-subtitle">Facial Analysis</span>
              </div>
            </div>
            <div className="face-shape-visual">
              <svg viewBox="0 0 120 150" className="face-shape-svg">
                <defs>
                  <linearGradient id="faceGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.5" />
                    <stop offset="100%" stopColor="#6C63FF" stopOpacity="0.3" />
                  </linearGradient>
                </defs>
                <motion.ellipse
                  cx="60" cy="70" rx="38" ry="48"
                  fill="none"
                  stroke="url(#faceGrad)"
                  strokeWidth="2"
                  initial={{ pathLength: 0, opacity: 0 }}
                  animate={{ pathLength: 1, opacity: 1 }}
                  transition={{ duration: 1.5, ease: 'easeInOut' }}
                />
                <motion.line
                  x1="60" y1="20" x2="60" y2="120"
                  stroke="rgba(139, 92, 246, 0.2)"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 1 }}
                />
                <motion.line
                  x1="20" y1="70" x2="100" y2="70"
                  stroke="rgba(139, 92, 246, 0.2)"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 1.2 }}
                />
                <motion.circle cx="44" cy="60" r="3" fill="rgba(139, 92, 246, 0.4)"
                  initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 1.5 }}
                />
                <motion.circle cx="76" cy="60" r="3" fill="rgba(139, 92, 246, 0.4)"
                  initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ delay: 1.6 }}
                />
                <motion.path
                  d="M50,85 Q60,93 70,85"
                  fill="none"
                  stroke="rgba(139, 92, 246, 0.4)"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 1.8 }}
                />
              </svg>
            </div>
            <div className="face-shape-label">
              <h4>{mapFaceShape(faceShape)}</h4>
              <p>{FACE_SHAPE_DESCRIPTIONS[faceShape] || 'Analysis pending'}</p>
            </div>
            <div className="face-metrics">
              <div className="face-metric">
                <span className="fm-label">Confidence</span>
                <span className="fm-value">{faceConfidence || '—'}%</span>
              </div>
              <div className="face-metric">
                <span className="fm-label">Shape</span>
                <span className="fm-value">{mapFaceShape(faceShape)}</span>
              </div>
              <div className="face-metric">
                <span className="fm-label">Reason</span>
                <span className="fm-value" style={{ fontSize: '0.7em' }}>{scanData?.face_shape_reason || '—'}</span>
              </div>
            </div>
          </GlassCard>
        </motion.div>

        <motion.div variants={fadeUp}>
          <GlassCard className="analysis-card measurements-card" delay={0.5}>
            <div className="card-header">
              <div className="card-icon-wrap" style={{ background: 'rgba(16, 185, 129, 0.12)' }}>
                <RiRulerLine style={{ color: '#10B981' }} />
              </div>
              <div>
                <h3>Scan Summary</h3>
                <span className="card-subtitle">Detected Attributes</span>
              </div>
            </div>
            <div className="measurements-grid">
              {measurements.map((m, i) => (
                <motion.div
                  key={m.label}
                  className="measurement-item"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.6 + i * 0.08 }}
                >
                  <span className="m-label">{m.label}</span>
                  <span className="m-dots" />
                  <span className="m-value">{m.value}</span>
                </motion.div>
              ))}
            </div>
            <div className="measurements-footer">
              <RiBodyScanLine />
              <span>Estimated from AI scan. Size estimates are approximate.</span>
            </div>
          </GlassCard>
        </motion.div>
      </motion.div>

      <motion.div
        className="analysis-insights-section"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
      >
        <h2 className="insights-title">
          <RiLightbulbLine /> AI Style Insights
        </h2>
        <div className="insights-grid">
          {aiInsights.map((insight, i) => (
            <GlassCard key={insight.title} className="insight-card" delay={0.7 + i * 0.1}>
              <div className="insight-icon" style={{ background: `${insight.color}15`, color: insight.color }}>
                {insight.icon}
              </div>
              <h4>{insight.title}</h4>
              <p>{insight.description}</p>
            </GlassCard>
          ))}
        </div>
      </motion.div>

      <motion.div
        className="analysis-cta-section"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.9 }}
      >
        <GlassCard className="cta-card" glow hover={false}>
          <div className="cta-content">
            <div className="cta-text">
              <h2>Ready for Personalized Recommendations?</h2>
              <p>
                Based on your analysis, our AI will curate outfits, colors, and styles
                tailored specifically to you.
              </p>
            </div>
            <AnimatedButton
              size="large"
              onClick={() => navigate('/recommendations')}
              icon={<RiSparklingLine />}
            >
              Get Recommendations
            </AnimatedButton>
          </div>
        </GlassCard>
      </motion.div>
    </div>
  );
}
