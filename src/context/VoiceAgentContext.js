import { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSession } from './SessionContext';
import { useTheme } from './ThemeContext';
import { useAuth } from './AuthContext';
import { PresenceState } from '../hooks/usePersonPresence';
import { apiPostJSON, apiPost, API_BASE_URL } from '../utils/api';

// "off" disables spoken replies (see playTTS). Anything else = voice on.
const ARIA_VOICE_ENABLED = (process.env.REACT_APP_ARIA_VOICE || 'on').toLowerCase() !== 'off';

const VoiceAgentContext = createContext();

const SPEECH_START_RMS = 0.035;
const SPEECH_STOP_RMS = 0.02;
const SILENCE_STOP_MS = 1200;
const MIN_SPEECH_MS = 300;
const MAX_RECORDING_MS = 15000;

export function VoiceAgentProvider({ children }) {
  const navigate = useNavigate();
  const {
    sessionId, setPendingRecommendations, setHighlightedItemId,
    addToCart, queueOutfitActions, showToast, presenceState,
    conversationGreeting, registerVoiceCallbacks,
  } = useSession();
  const { toggleTheme } = useTheme();
  const { logout } = useAuth();

  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [handsFreeMode, setHandsFreeMode] = useState(false);
  const [handsFreeStatus, setHandsFreeStatus] = useState('off');

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const micStreamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const vadRafRef = useRef(null);
  const speechStartedAtRef = useRef(null);
  const silenceStartedAtRef = useRef(null);
  const handsFreeRecorderRef = useRef(null);
  const gateRef = useRef({ isRecording: false, isTyping: false, isSpeaking: false, personPresent: false });
  const currentAudioRef = useRef(null);

  useEffect(() => {
    gateRef.current.isRecording = isRecording;
    gateRef.current.isTyping = isTyping;
    gateRef.current.isSpeaking = isSpeaking;
  }, [isRecording, isTyping, isSpeaking]);

  const getTimeNow = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const addMessage = useCallback(({ sender, text }) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), sender, text, time: getTimeNow() }]);
  }, []);

  const playTTS = useCallback(async (text) => {
    // Kill switch for Aria's voice: REACT_APP_ARIA_VOICE=off in .env silences
    // every spoken reply (greeting, chat, proactive events) while leaving the
    // text replies, toasts and on-screen actions untouched. Every TTS call in
    // the app routes through here (SessionContext uses the registered
    // callback), so this is the single place to gate it.
    if (ARIA_VOICE_ENABLED === false) return;
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    setIsSpeaking(true);
    try {
      const res = await apiPost('/api/voice/tts', { text });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      currentAudioRef.current = audio;
      audio.onended = () => { setIsSpeaking(false); URL.revokeObjectURL(url); currentAudioRef.current = null; };
      audio.onerror = () => { setIsSpeaking(false); URL.revokeObjectURL(url); currentAudioRef.current = null; };
      audio.play();
    } catch {
      setIsSpeaking(false);
    }
  }, []);

  const handleActions = useCallback((actions) => {
    const outfitBatch = [];
    // Opening the scanner wins over any other page change in the same batch;
    // otherwise a later navigate would pull her straight off the scan.
    const scanRequested = (actions || []).some((a) => a.type === 'start_scan');
    for (const action of actions || []) {
      if (scanRequested && ['navigate', 'show_recommendations', 'show_item'].includes(action.type)) {
        if (action.type === 'show_recommendations') {
          setPendingRecommendations({
            results: action.payload?.results || [],
            sections: action.payload?.sections || null,
          });
        }
        continue;
      }
      switch (action.type) {
        case 'navigate':
          navigate(`/${action.payload?.page || 'dashboard'}`);
          break;
        case 'start_scan':
          navigate('/body-scanner');
          break;
        case 'show_recommendations':
          // Whole payload: {results, sections?} -- sections present for the
          // post-scan complete look (see Recommendations.js).
          setPendingRecommendations({
            results: action.payload?.results || [],
            sections: action.payload?.sections || null,
          });
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
        case 'escalate_to_staff':
          showToast("I've let a store associate know -- they'll be with you shortly.", 'info');
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
        default:
          break;
      }
    }
    if (outfitBatch.length > 0) {
      queueOutfitActions(outfitBatch);
      navigate('/outfit-builder');
    }
  }, [navigate, setPendingRecommendations, setHighlightedItemId, addToCart, queueOutfitActions, showToast, toggleTheme, logout]);

  // Register callbacks so SessionContext.fireAgentEvent delegates TTS/messages here
  useEffect(() => {
    registerVoiceCallbacks({ playTTS, addMessage, handleActions });
    return () => registerVoiceCallbacks({});
  }, [registerVoiceCallbacks, playTTS, addMessage, handleActions]);

  // Greeting flow
  const greetedSessionRef = useRef(null);
  useEffect(() => {
    if (presenceState !== PresenceState.CONVERSATION_ACTIVE) return;
    if (greetedSessionRef.current === sessionId) return;
    if (!conversationGreeting || conversationGreeting.sessionId !== sessionId) {
      setIsTyping(true);
      return;
    }
    greetedSessionRef.current = sessionId;
    setIsTyping(false);
    setMessages([{ id: Date.now(), sender: 'ai', text: conversationGreeting.reply, time: getTimeNow() }]);
    handleActions(conversationGreeting.actions);
    playTTS(conversationGreeting.reply);
  }, [presenceState, sessionId, conversationGreeting, handleActions, playTTS]);

  // Goodbye when person leaves — Aria says bye before the session resets
  const prevPresenceForByeRef = useRef(presenceState);
  useEffect(() => {
    const prev = prevPresenceForByeRef.current;
    prevPresenceForByeRef.current = presenceState;
    if (prev === PresenceState.CONVERSATION_ACTIVE && presenceState === PresenceState.NO_PERSON) {
      const goodbyes = [
        "Bye! It was great styling with you. Come back anytime!",
        "See you later! Remember, you look amazing today!",
        "Goodbye! Can't wait to help you style again!",
        "Take care! You're going to look fantastic!",
      ];
      const msg = goodbyes[Math.floor(Math.random() * goodbyes.length)];
      addMessage({ sender: 'ai', text: msg });
      playTTS(msg);
    }
  }, [presenceState, addMessage, playTTS]);

  // Reset messages when session resets (person left and came back)
  const prevSessionRef = useRef(sessionId);
  useEffect(() => {
    if (sessionId && sessionId !== prevSessionRef.current) {
      setMessages([]);
      prevSessionRef.current = sessionId;
    }
  }, [sessionId]);

  const sendMessage = useCallback(async (text, fromVoice = false) => {
    if (!text.trim() || !sessionId) return;
    const userMsg = { id: Date.now(), sender: 'user', text: text.trim(), time: getTimeNow() };
    setMessages(prev => [...prev, userMsg]);
    setIsTyping(true);

    // Streaming path -- consume /api/chat/stream SSE, updating the AI
    // message in-place as delta chunks arrive so words appear at ~2s TTFT
    // instead of the customer staring at "..." for 30-60s. Tool turns
    // arrive as a single 'fallback' event with the full result.
    const aiMsgId = Date.now() + 1;
    const placeholderMsg = { id: aiMsgId, sender: 'ai', text: '', time: getTimeNow(), streaming: true };
    setMessages(prev => [...prev, placeholderMsg]);

    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text.trim() }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalReply = '';
      let finalActions = [];
      let sawFirstDelta = false;
      let sawTerminalEvent = false;

      // SSE parser: events are separated by \n\n, each event has
      //   event: <type>\ndata: <json>\n
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';  // last chunk may be incomplete
        for (const evt of events) {
          const lines = evt.split('\n');
          let evtType = '', dataStr = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) evtType = line.slice(7).trim();
            else if (line.startsWith('data: ')) dataStr = line.slice(6);
          }
          if (!dataStr) continue;
          let payload;
          try { payload = JSON.parse(dataStr); } catch { continue; }

          if (evtType === 'delta' && payload.text) {
            if (!sawFirstDelta) {
              setIsTyping(false);
              sawFirstDelta = true;
            }
            finalReply += payload.text;
            const soFar = finalReply;
            setMessages(prev => prev.map(m =>
              m.id === aiMsgId ? { ...m, text: soFar } : m
            ));
          } else if (evtType === 'fallback' || evtType === 'done') {
            sawTerminalEvent = true;
            finalReply = payload.reply || finalReply;
            finalActions = payload.actions || [];
            setIsTyping(false);
            setMessages(prev => prev.map(m =>
              m.id === aiMsgId ? { ...m, text: finalReply, streaming: false } : m
            ));
          }
        }
      }

      // Safety net: the backend's leak-detection can abandon a partial delta
      // mid-stream and re-route to a slower recovery call (see graph.py's
      // _looks_like_json_leak) -- if THAT itself never resolves cleanly, the
      // stream can end with deltas already shown but no fallback/done event
      // ever arriving, leaving a raw JSON fragment stuck on screen forever.
      // Confirmed live. Never leave that displayed -- replace it.
      if (!sawTerminalEvent) {
        finalReply = "Sorry, I got a bit tangled up there -- could you say that again?";
        setIsTyping(false);
        setMessages(prev => prev.map(m =>
          m.id === aiMsgId ? { ...m, text: finalReply, streaming: false } : m
        ));
      }

      handleActions(finalActions);
      if (fromVoice && finalReply) playTTS(finalReply);
    } catch (err) {
      setIsTyping(false);
      setMessages(prev => prev.map(m =>
        m.id === aiMsgId
          ? { ...m, text: `Sorry, I had trouble responding. ${err.message || 'Please try again.'}`, streaming: false }
          : m
      ));
    }
  }, [sessionId, playTTS, handleActions]);

  const processRecordedAudio = useCallback(async (audioBlob) => {
    if (audioBlob.size === 0) return;
    setIsTyping(true);
    try {
      const form = new FormData();
      form.append('audio', audioBlob, 'speech.webm');
      const sttResult = await apiPostJSON('/api/voice/stt', form, true);
      const transcript = sttResult.text || sttResult.transcript || '';
      setIsTyping(false);
      if (transcript.trim()) {
        sendMessage(transcript, true);
      } else {
        addMessage({ sender: 'ai', text: "I didn't catch that -- could you speak a bit louder or closer to the mic?" });
      }
    } catch (err) {
      setIsTyping(false);
      addMessage({ sender: 'ai', text: `Sorry, I couldn't hear that -- ${err.message || 'transcription failed'}.` });
    }
  }, [sendMessage, addMessage]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        if (audioBlob.size === 0) {
          addMessage({ sender: 'ai', text: "I didn't catch any speech in that recording -- could you try again?" });
          return;
        }
        processRecordedAudio(audioBlob);
      };
      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      setIsRecording(false);
      addMessage({ sender: 'ai', text: `I can't access your microphone -- ${err.message || 'permission denied'}.` });
    }
  }, [processRecordedAudio, addMessage]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  // --- Hands-free VAD ---
  useEffect(() => {
    const personPresent = presenceState === PresenceState.CONVERSATION_ACTIVE;
    gateRef.current.personPresent = personPresent;
    setHandsFreeStatus(prev => {
      if (prev === 'listening' || !handsFreeMode) return prev;
      return personPresent ? 'present' : 'waiting';
    });
  }, [presenceState, handsFreeMode]);

  const beginHandsFreeRecording = useCallback(() => {
    const stream = micStreamRef.current;
    if (!stream) return;
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = () => processRecordedAudio(new Blob(chunks, { type: 'audio/webm' }));
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
        if (cancelled) { micStream.getTracks().forEach(t => t.stop()); return; }
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
        if (!cancelled) {
          setHandsFreeMode(false);
          showToast(`Couldn't start hands-free mode -- ${err.message || 'microphone access denied'}`, 'error');
        }
      }
    })();
    return () => {
      cancelled = true;
      if (vadRafRef.current) cancelAnimationFrame(vadRafRef.current);
      if (handsFreeRecorderRef.current && handsFreeRecorderRef.current.state !== 'inactive') handsFreeRecorderRef.current.stop();
      micStreamRef.current?.getTracks().forEach(t => t.stop());
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
  }, [handsFreeMode, runVadLoop, showToast]);

  useEffect(() => {
    setHandsFreeMode(presenceState === PresenceState.CONVERSATION_ACTIVE);
  }, [presenceState]);

  const toggleHandsFree = useCallback(() => {
    if (isRecording && !handsFreeMode) return;
    setHandsFreeMode(prev => !prev);
  }, [isRecording, handsFreeMode]);

  return (
    <VoiceAgentContext.Provider value={{
      messages, sendMessage, addMessage, isTyping, isRecording, isSpeaking,
      handsFreeMode, handsFreeStatus, toggleHandsFree,
      startRecording, stopRecording, playTTS, handleActions, presenceState,
    }}>
      {children}
    </VoiceAgentContext.Provider>
  );
}

export const useVoiceAgent = () => useContext(VoiceAgentContext);
