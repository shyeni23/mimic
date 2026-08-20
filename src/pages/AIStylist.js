import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiSparklingLine, RiSendPlaneFill, RiMicLine,
  RiUserLine, RiStopCircleLine, RiEyeLine, RiEyeOffLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import { useSession } from '../context/SessionContext';
import { useTheme } from '../context/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { apiPostJSON, apiPost } from '../utils/api';
import { PresenceState } from '../hooks/usePersonPresence';
import './AIStylist.css';

// Phase C (always-listening): tuned for typical laptop/webcam mic input.
// RMS is computed from time-domain samples normalized to roughly 0..1.
const SPEECH_START_RMS = 0.035;
const SPEECH_STOP_RMS = 0.02;
const SILENCE_STOP_MS = 1200;
const MIN_SPEECH_MS = 300;
const MAX_RECORDING_MS = 15000;

const quickQuestions = [
  "What should I wear today?",
  "Style a date night outfit",
  "What colors suit me best?",
  "Suggest a capsule wardrobe",
];

export default function AIStylist() {
  const navigate = useNavigate();
  const {
    sessionId, setPendingRecommendations, setHighlightedItemId,
    addToCart, queueOutfitActions, showToast, presenceState, conversationGreeting,
  } = useSession();
  const { toggleTheme } = useTheme();
  const { logout } = useAuth();
  // Starts empty -- the opening message is the LLM-generated greeting from
  // the presence-triggered conversation session (see the effect below), not
  // a hardcoded string. Manually opening this page without a detected person
  // (e.g. admin testing) just leaves the transcript empty until you type.
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);

  // Phase C: hands-free always-listening mode. `handsFreeStatus` drives the
  // status pill in the header: 'off' | 'starting' | 'waiting' (no one in
  // frame yet) | 'present' (person detected, listening for speech) |
  // 'listening' (actively recording an utterance via VAD).
  const [handsFreeMode, setHandsFreeMode] = useState(false);
  const [handsFreeStatus, setHandsFreeStatus] = useState('off');

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // Hands-free infrastructure -- persistent while handsFreeMode is on.
  // NOTE: camera + presence detection is NOT owned here -- it's a single
  // global camera/state machine (usePersonPresence, mounted once in
  // SessionContext) that this page just reads via `presenceState`. This
  // page only owns the MIC side of hands-free (recording + VAD).
  const micStreamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const vadRafRef = useRef(null);
  const speechStartedAtRef = useRef(null);
  const silenceStartedAtRef = useRef(null);
  const handsFreeRecorderRef = useRef(null);
  // RAF loop reads these every frame -- refs avoid stale closures without
  // needing to tear down/rebuild the loop on every state change.
  const gateRef = useRef({ isRecording: false, isTyping: false, isSpeaking: false, personPresent: false });

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  useEffect(() => {
    gateRef.current.isRecording = isRecording;
    gateRef.current.isTyping = isTyping;
    gateRef.current.isSpeaking = isSpeaking;
  }, [isRecording, isTyping, isSpeaking]);

  const getTimeNow = () => {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const playTTS = useCallback(async (text) => {
    setIsSpeaking(true);
    try {
      const res = await apiPost('/api/voice/tts', { text });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
      };
      audio.play();
    } catch {
      setIsSpeaking(false);
    }
  }, []);

  // Phase B (Module 2 build guide, section 7): /api/chat's response carries
  // an `actions[]` array alongside `reply` -- these are UI actions the agent
  // decided to trigger hands-free (start a scan, pull up recommendations,
  // add to cart...). Executing them is what makes Aria actually drive the
  // mirror app instead of just talking about it.
  const handleActions = useCallback((actions) => {
    const outfitBatch = [];
    for (const action of actions || []) {
      switch (action.type) {
        case 'navigate':
          navigate(`/${action.payload?.page || 'dashboard'}`);
          break;
        case 'start_scan':
          navigate('/body-scanner');
          break;
        case 'show_recommendations':
          setPendingRecommendations(action.payload?.results || []);
          navigate('/recommendations');
          break;
        case 'show_item':
          setHighlightedItemId(action.payload?.item_id || null);
          navigate('/recommendations');
          break;
        case 'add_to_cart':
          addToCart(action.payload?.item_id);
          showToast('Added to your fitting room', 'success');
          break;
        case 'start_tryon':
          showToast('Virtual try-on is coming soon!', 'info');
          break;
        case 'toggle_theme':
          toggleTheme();
          break;
        case 'admin_logout':
          logout();
          navigate('/');
          break;
        case 'select_outfit_category':
        case 'set_outfit_item':
        case 'remove_outfit_item':
        case 'set_outfit_name':
        case 'save_outfit':
          outfitBatch.push(action);
          break;
        case 'admin_update_stock':
        case 'admin_show_analytics':
          break;
        default:
          break;
      }
    }
    if (outfitBatch.length > 0) {
      queueOutfitActions(outfitBatch);
      navigate('/outfit-builder');
    }
  }, [navigate, setPendingRecommendations, setHighlightedItemId, addToCart, queueOutfitActions, showToast, toggleTheme, logout]);

  // person_detected -> session created -> conversational agent started (see
  // SessionContext.startConversationSession) -> this renders the resulting
  // LLM-generated greeting as message #1, once, for that session. Shows the
  // existing typing indicator for the brief round-trip while it's in flight.
  // Not hardcoded: the actual words come from the agent graph/persona (see
  // backend/app/services/agent/events.py's "conversation_start" trigger).
  const greetedSessionRef = useRef(null);

  useEffect(() => {
    if (presenceState !== PresenceState.CONVERSATION_ACTIVE) return;
    if (greetedSessionRef.current === sessionId) return; // already greeted this session

    if (!conversationGreeting || conversationGreeting.sessionId !== sessionId) {
      setIsTyping(true); // greeting still in flight
      return;
    }

    greetedSessionRef.current = sessionId;
    setIsTyping(false);
    setMessages([{
      id: Date.now(),
      sender: 'ai',
      text: conversationGreeting.reply,
      time: getTimeNow(),
    }]);
    handleActions(conversationGreeting.actions);
    playTTS(conversationGreeting.reply);
  }, [presenceState, sessionId, conversationGreeting, handleActions, playTTS]);

  const sendMessage = useCallback(async (text, fromVoice = false) => {
    if (!text.trim() || !sessionId) return;

    const userMsg = {
      id: Date.now(),
      sender: 'user',
      text: text.trim(),
      time: getTimeNow(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputText('');
    setIsTyping(true);

    try {
      const data = await apiPostJSON('/api/chat', {
        session_id: sessionId,
        message: text.trim(),
      });

      const aiMsg = {
        id: Date.now() + 1,
        sender: 'ai',
        text: data.reply,
        time: getTimeNow(),
      };
      setIsTyping(false);
      setMessages((prev) => [...prev, aiMsg]);
      handleActions(data.actions);

      if (fromVoice) {
        playTTS(data.reply);
      }
    } catch (err) {
      setIsTyping(false);
      const errMsg = {
        id: Date.now() + 1,
        sender: 'ai',
        text: `Sorry, I had trouble responding. ${err.message || 'Please try again.'}`,
        time: getTimeNow(),
      };
      setMessages((prev) => [...prev, errMsg]);
    }
  }, [sessionId, playTTS, handleActions]);

  const handleSubmit = (e) => {
    e.preventDefault();
    sendMessage(inputText);
  };

  const handleQuickQuestion = (question) => {
    sendMessage(question);
  };

  // Shared by manual push-to-talk (Phase A/B) and hands-free VAD (Phase C) --
  // both just need to hand off a recorded blob and get it through
  // STT -> chat -> TTS the same way.
  const processRecordedAudio = useCallback(async (audioBlob) => {
    if (audioBlob.size === 0) return;

    setIsTyping(true);
    try {
      const form = new FormData();
      form.append('audio', audioBlob, 'speech.webm');
      const sttResult = await apiPostJSON('/api/voice/stt', form, true);
      const transcript = sttResult.text || sttResult.transcript || '';
      if (transcript.trim()) {
        setIsTyping(false);
        sendMessage(transcript, true);
      } else {
        setIsTyping(false);
      }
    } catch (err) {
      console.error('[voice] STT request failed:', err);
      setIsTyping(false);
      setMessages((prev) => [...prev, {
        id: Date.now(),
        sender: 'ai',
        text: `Sorry, I couldn't hear that -- ${err.message || 'transcription failed'}.`,
        time: getTimeNow(),
      }]);
    }
  }, [sendMessage]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        if (audioBlob.size === 0) {
          setMessages((prev) => [...prev, {
            id: Date.now(),
            sender: 'ai',
            text: "I didn't catch any speech in that recording -- could you try again?",
            time: getTimeNow(),
          }]);
          return;
        }
        processRecordedAudio(audioBlob);
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('[voice] Could not access microphone:', err);
      setIsRecording(false);
      setMessages((prev) => [...prev, {
        id: Date.now(),
        sender: 'ai',
        text: `I can't access your microphone -- ${err.message || 'permission denied'}. Check your browser's mic permissions for this site.`,
        time: getTimeNow(),
      }]);
    }
  }, [processRecordedAudio]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  // ---------------- Phase C: always-listening hands-free mode ----------------

  // Mirror the globally-detected presence state (see usePersonPresence,
  // mounted once in SessionContext) into this page's VAD gate + status pill.
  // Presence is detected exactly once, in exactly one place -- this page
  // never touches the camera.
  useEffect(() => {
    const personPresent = presenceState === PresenceState.CONVERSATION_ACTIVE;
    gateRef.current.personPresent = personPresent;
    setHandsFreeStatus((prev) => {
      if (prev === 'listening' || !handsFreeMode) return prev;
      return personPresent ? 'present' : 'waiting';
    });
  }, [presenceState, handsFreeMode]);

  const beginHandsFreeRecording = useCallback(() => {
    const stream = micStreamRef.current;
    if (!stream) return;
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      const audioBlob = new Blob(chunks, { type: 'audio/webm' });
      processRecordedAudio(audioBlob);
    };
    recorder.__startedAt = Date.now();
    handsFreeRecorderRef.current = recorder;
    recorder.start();
    setIsRecording(true);
    setHandsFreeStatus('listening');
  }, [processRecordedAudio]);

  const endHandsFreeRecording = useCallback(() => {
    if (handsFreeRecorderRef.current && handsFreeRecorderRef.current.state !== 'inactive') {
      handsFreeRecorderRef.current.stop();
    }
    handsFreeRecorderRef.current = null;
    setIsRecording(false);
    setHandsFreeStatus('present');
  }, []);

  const runVadLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const data = new Uint8Array(analyser.fftSize);

    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const norm = (data[i] - 128) / 128;
        sumSquares += norm * norm;
      }
      const rms = Math.sqrt(sumSquares / data.length);
      const now = Date.now();
      const gate = gateRef.current;
      const recorder = handsFreeRecorderRef.current;
      const isAutoRecording = !!recorder && recorder.state === 'recording';

      if (!isAutoRecording) {
        // Only start listening if nothing else is using the mic/chat pipeline,
        // and a person is actually in frame.
        if (!gate.isRecording && !gate.isTyping && !gate.isSpeaking && gate.personPresent) {
          if (rms > SPEECH_START_RMS) {
            if (!speechStartedAtRef.current) speechStartedAtRef.current = now;
            if (now - speechStartedAtRef.current > MIN_SPEECH_MS) {
              speechStartedAtRef.current = null;
              beginHandsFreeRecording();
            }
          } else {
            speechStartedAtRef.current = null;
          }
        }
      } else {
        // Actively recording an utterance -- watch for sustained silence or
        // a hard cap so we don't record forever.
        if (rms < SPEECH_STOP_RMS) {
          if (!silenceStartedAtRef.current) silenceStartedAtRef.current = now;
          if (now - silenceStartedAtRef.current > SILENCE_STOP_MS) {
            silenceStartedAtRef.current = null;
            endHandsFreeRecording();
          }
        } else {
          silenceStartedAtRef.current = null;
        }
        if (recorder.__startedAt && now - recorder.__startedAt > MAX_RECORDING_MS) {
          endHandsFreeRecording();
        }
      }

      vadRafRef.current = requestAnimationFrame(tick);
    };

    vadRafRef.current = requestAnimationFrame(tick);
  }, [beginHandsFreeRecording, endHandsFreeRecording]);

  useEffect(() => {
    if (!handsFreeMode) return undefined;

    let cancelled = false;
    setHandsFreeStatus('starting');

    (async () => {
      try {
        const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          micStream.getTracks().forEach((t) => t.stop());
          return;
        }
        micStreamRef.current = micStream;

        const AudioContextCls = window.AudioContext || window.webkitAudioContext;
        const audioCtx = new AudioContextCls();
        const source = audioCtx.createMediaStreamSource(micStream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        audioCtxRef.current = audioCtx;
        analyserRef.current = analyser;

        setHandsFreeStatus(gateRef.current.personPresent ? 'present' : 'waiting');
        runVadLoop();
      } catch (err) {
        console.error('[hands-free] mic setup failed:', err);
        if (!cancelled) {
          setHandsFreeMode(false);
          setMessages((prev) => [...prev, {
            id: Date.now(),
            sender: 'ai',
            text: `Couldn't start hands-free mode -- ${err.message || 'microphone access denied'}.`,
            time: getTimeNow(),
          }]);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (vadRafRef.current) cancelAnimationFrame(vadRafRef.current);
      if (handsFreeRecorderRef.current && handsFreeRecorderRef.current.state !== 'inactive') {
        handsFreeRecorderRef.current.stop();
      }
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close().catch(() => {});
      micStreamRef.current = null;
      audioCtxRef.current = null;
      analyserRef.current = null;
      handsFreeRecorderRef.current = null;
      speechStartedAtRef.current = null;
      silenceStartedAtRef.current = null;
      setHandsFreeStatus('off');
      setIsRecording(false);
    };
  }, [handsFreeMode, runVadLoop]);

  // The actual "trigger the conversational system" step: hands-free mode
  // follows the globally-detected presence state directly, so a person
  // stepping into view arms the mic automatically, and them leaving ends/
  // resets the interaction (tears down the mic/VAD via the cleanup above).
  // The manual toggle below still works as an in-between override (e.g. to
  // end a conversation early while the person is still in frame).
  useEffect(() => {
    setHandsFreeMode(presenceState === PresenceState.CONVERSATION_ACTIVE);
  }, [presenceState]);

  const toggleHandsFree = () => {
    if (isRecording && !handsFreeMode) return; // don't fight manual push-to-talk mid-recording
    setHandsFreeMode((prev) => !prev);
  };

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
              <h2>MirrorAI Stylist</h2>
              <span className="chat-status">
                {isSpeaking
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
                  : 'Online · Ready to style'}
              </span>
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
              onClick={() => handleQuickQuestion(q)}
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
            onClick={toggleRecording}
            whileTap={{ scale: 0.9 }}
            disabled={isTyping || handsFreeMode}
            title={handsFreeMode ? 'Turn off hands-free mode to use push-to-talk' : undefined}
          >
            {isRecording ? <RiStopCircleLine /> : <RiMicLine />}
            {isRecording && <span className="voice-pulse" />}
            {isRecording && <span className="voice-pulse delay" />}
          </motion.button>

          <input
            ref={inputRef}
            type="text"
            className="chat-input"
            placeholder={isRecording ? 'Listening...' : handsFreeMode ? 'Hands-free mode is on...' : 'Ask your AI stylist anything...'}
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
