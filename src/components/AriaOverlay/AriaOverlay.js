import { useState, useRef, useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { RiSparklingLine, RiSendPlaneFill, RiMicLine, RiStopCircleLine, RiCloseLine, RiUserLine } from 'react-icons/ri';
import { useVoiceAgent } from '../../context/VoiceAgentContext';
import './AriaOverlay.css';

const STATUS_LABELS = {
  off: null,
  starting: 'Starting...',
  waiting: 'Waiting for you',
  present: 'Listening',
  listening: 'Hearing you...',
};

export default function AriaOverlay() {
  const location = useLocation();
  const {
    messages, sendMessage, isTyping, isRecording, isSpeaking,
    handsFreeMode, handsFreeStatus, toggleHandsFree,
    startRecording, stopRecording,
  } = useVoiceAgent();

  const [expanded, setExpanded] = useState(false);
  const [inputText, setInputText] = useState('');
  const [lastBubble, setLastBubble] = useState(null);
  const messagesEndRef = useRef(null);
  const bubbleTimerRef = useRef(null);

  const hidden = location.pathname === '/stylist';
  const prevAiCountRef = useRef(0);

  const latestAiMsg = useMemo(
    () => messages.filter(m => m.sender === 'ai').slice(-1)[0],
    [messages],
  );

  // Auto-expand the panel when the first AI message arrives (greeting on
  // person detection). This makes Aria visibly initiate — no click needed.
  useEffect(() => {
    const aiCount = messages.filter(m => m.sender === 'ai').length;
    if (aiCount > 0 && prevAiCountRef.current === 0 && !hidden) {
      setExpanded(true);
    }
    prevAiCountRef.current = aiCount;
  }, [messages, hidden]);

  useEffect(() => {
    if (hidden || !latestAiMsg || expanded) return;
    if (lastBubble?.id === latestAiMsg.id) return;
    setLastBubble(latestAiMsg);
    if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current);
    bubbleTimerRef.current = setTimeout(() => setLastBubble(null), 6000);
    return () => { if (bubbleTimerRef.current) clearTimeout(bubbleTimerRef.current); };
  }, [latestAiMsg, expanded, lastBubble?.id, hidden]);

  useEffect(() => {
    if (expanded && !hidden) messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping, expanded, hidden]);

  // Collapse panel when navigating to stylist
  useEffect(() => {
    if (hidden) setExpanded(false);
  }, [hidden]);

  if (hidden) return null;

  const orbState = isSpeaking ? 'speaking' : isTyping ? 'thinking' : isRecording ? 'recording' : handsFreeMode && handsFreeStatus === 'present' ? 'active' : 'idle';
  const statusLabel = isSpeaking ? 'Speaking...' : isTyping ? 'Thinking...' : STATUS_LABELS[handsFreeStatus];

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    sendMessage(inputText);
    setInputText('');
  };

  return (
    <div className="aria-overlay">
      <AnimatePresence>
        {lastBubble && !expanded && (
          <motion.div
            className="aria-speech-bubble"
            initial={{ opacity: 0, y: 10, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.9 }}
            transition={{ type: 'spring', stiffness: 300, damping: 25 }}
            onClick={() => { setExpanded(true); setLastBubble(null); }}
          >
            <p>{lastBubble.text.length > 120 ? lastBubble.text.slice(0, 120) + '...' : lastBubble.text}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {expanded && (
          <motion.div
            className="aria-panel"
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 300, damping: 28 }}
          >
            <div className="aria-panel-header">
              <div className="aria-panel-title">
                <div className={`aria-mini-avatar ${orbState}`}><RiSparklingLine /></div>
                <div>
                  <strong>Aria</strong>
                  <span className="aria-panel-status">{statusLabel || 'Ready'}</span>
                </div>
              </div>
              <div className="aria-panel-controls">
                <button
                  className={`aria-hf-btn ${handsFreeMode ? 'active' : ''}`}
                  onClick={toggleHandsFree}
                  title={handsFreeMode ? 'Hands-free on' : 'Hands-free off'}
                >
                  {handsFreeMode ? 'HF On' : 'HF Off'}
                </button>
                <button className="aria-close-btn" onClick={() => setExpanded(false)}>
                  <RiCloseLine />
                </button>
              </div>
            </div>

            <div className="aria-panel-messages">
              {messages.length === 0 && !isTyping && (
                <div className="aria-empty">Say something or type below...</div>
              )}
              {messages.map((msg) => (
                <div key={msg.id} className={`aria-msg ${msg.sender}`}>
                  <div className="aria-msg-avatar">
                    {msg.sender === 'ai' ? <RiSparklingLine /> : <RiUserLine />}
                  </div>
                  <div className="aria-msg-text">{msg.text}</div>
                </div>
              ))}
              {isTyping && (
                <div className="aria-msg ai">
                  <div className="aria-msg-avatar"><RiSparklingLine /></div>
                  <div className="aria-msg-text aria-typing">
                    <span className="aria-dot" /><span className="aria-dot" /><span className="aria-dot" />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form className="aria-panel-input" onSubmit={handleSubmit}>
              <button
                type="button"
                className={`aria-mic-btn ${isRecording ? 'recording' : ''}`}
                onClick={isRecording ? stopRecording : startRecording}
                disabled={isTyping || handsFreeMode}
              >
                {isRecording ? <RiStopCircleLine /> : <RiMicLine />}
              </button>
              <input
                type="text"
                placeholder={handsFreeMode ? 'Hands-free active...' : 'Talk to Aria...'}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                disabled={isRecording || isTyping}
              />
              <button type="submit" className="aria-send-btn" disabled={!inputText.trim() || isTyping}>
                <RiSendPlaneFill />
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        className={`aria-orb ${orbState} ${expanded ? 'expanded' : ''}`}
        onClick={() => { setExpanded(true); setLastBubble(null); }}
        whileTap={{ scale: 0.92 }}
        layout
      >
        <span className="aria-orb-icon"><RiSparklingLine /></span>
        {orbState === 'recording' && <span className="aria-orb-ring recording" />}
        {orbState === 'speaking' && <span className="aria-orb-ring speaking" />}
        {orbState === 'thinking' && <span className="aria-orb-ring thinking" />}
        {orbState === 'active' && <span className="aria-orb-ring active" />}
        {statusLabel && !expanded && <span className="aria-orb-label">{statusLabel}</span>}
      </motion.button>
    </div>
  );
}
