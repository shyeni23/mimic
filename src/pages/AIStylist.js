import { useRef, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiSparklingLine, RiSendPlaneFill, RiMicLine,
  RiUserLine, RiStopCircleLine, RiEyeLine, RiEyeOffLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import { useVoiceAgent } from '../context/VoiceAgentContext';
import { useSession } from '../context/SessionContext';
import './AIStylist.css';

const quickQuestions = [
  "What should I wear today?",
  "Style a date night outfit",
  "What colors suit me best?",
  "Suggest a capsule wardrobe",
];

export default function AIStylist() {
  const {
    messages, sendMessage, isTyping, isRecording, isSpeaking,
    handsFreeMode, handsFreeStatus, toggleHandsFree,
    startRecording, stopRecording,
  } = useVoiceAgent();

  const { fireAgentEvent } = useSession();
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Proactive: if the customer hasn't sent a message for ~45s, Aria checks in.
  // Resets on any new message. Fires at most once per idle window.
  const idleFiredRef = useRef(false);
  useEffect(() => {
    idleFiredRef.current = false;
    if (!messages.length) return undefined;
    const timer = setTimeout(() => {
      if (!idleFiredRef.current && fireAgentEvent) {
        idleFiredRef.current = true;
        fireAgentEvent('long_pause');
      }
    }, 45000);
    return () => clearTimeout(timer);
  }, [messages, fireAgentEvent]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!inputText.trim()) return;
    sendMessage(inputText);
    setInputText('');
  };

  const statusText = isSpeaking
    ? 'Speaking...'
    : isTyping
    ? 'Thinking...'
    : handsFreeMode
    ? {
        starting: 'Starting hands-free mode...',
        waiting: 'Hands-free: waiting for you to step into view',
        present: "Hands-free: I'm listening whenever you speak",
        listening: "Hands-free: hearing you now...",
        off: 'Online · Ready to style',
      }[handsFreeStatus]
    : 'Online · Ready to style';

  return (
    <div className="ai-stylist-page">
      <GlassCard className="chat-container" hover={false}>
        <div className="chat-header">
          <div className="chat-header-left">
            <div className="ai-chat-avatar">
              <RiSparklingLine />
              <span className="online-dot" />
            </div>
            <div className="chat-header-info">
              <h2>Aria - AI Stylist</h2>
              <span className="chat-status">{statusText}</span>
            </div>
          </div>
          <motion.button
            type="button"
            className={`hands-free-toggle ${handsFreeMode ? 'active' : ''}`}
            onClick={toggleHandsFree}
            whileTap={{ scale: 0.94 }}
            title={handsFreeMode ? 'Turn off hands-free listening' : 'Turn on hands-free listening'}
          >
            {handsFreeMode ? <RiEyeLine /> : <RiEyeOffLine />}
            <span>Hands-free</span>
          </motion.button>
        </div>

        <div className="chat-messages">
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                className={`chat-message ${msg.sender}`}
                initial={{ opacity: 0, y: 12, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.3 }}
                layout
              >
                <div className="message-avatar">
                  {msg.sender === 'ai' ? <RiSparklingLine /> : <RiUserLine />}
                </div>
                <div className="message-content">
                  <div className="message-bubble">
                    <p>{msg.text}</p>
                  </div>
                  <span className="message-time">{msg.time}</span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          <AnimatePresence>
            {isTyping && (
              <motion.div
                className="chat-message ai"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
              >
                <div className="message-avatar">
                  <RiSparklingLine />
                </div>
                <div className="message-content">
                  <div className="message-bubble typing-bubble">
                    <div className="typing-indicator">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} />
        </div>

        <div className="chat-suggestions">
          {quickQuestions.map((q) => (
            <motion.button
              key={q}
              className="suggestion-chip"
              onClick={() => sendMessage(q)}
              whileHover={{ scale: 1.04 }}
              whileTap={{ scale: 0.96 }}
              disabled={isTyping}
            >
              {q}
            </motion.button>
          ))}
        </div>

        <form className="chat-input-area" onSubmit={handleSubmit}>
          <motion.button
            type="button"
            className={`voice-btn ${isRecording ? 'recording' : ''}`}
            onClick={isRecording ? stopRecording : startRecording}
            whileTap={{ scale: 0.9 }}
            disabled={isTyping || handsFreeMode}
            title={handsFreeMode ? 'Turn off hands-free mode to use push-to-talk' : undefined}
          >
            {isRecording ? <RiStopCircleLine /> : <RiMicLine />}
            {isRecording && <span className="voice-pulse" />}
            {isRecording && <span className="voice-pulse delay" />}
          </motion.button>

          <input
            type="text"
            className="chat-input"
            placeholder={isRecording ? 'Listening...' : handsFreeMode ? 'Hands-free mode is on...' : 'Ask Aria anything...'}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={isRecording || isTyping}
          />

          <motion.button
            type="submit"
            className="send-btn"
            disabled={!inputText.trim() || isTyping}
            whileHover={{ scale: 1.08 }}
            whileTap={{ scale: 0.92 }}
          >
            <RiSendPlaneFill />
          </motion.button>
        </form>
      </GlassCard>
    </div>
  );
}
