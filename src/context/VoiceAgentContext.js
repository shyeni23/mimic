import { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useSession } from './SessionContext';
import { useTheme } from './ThemeContext';
import { useAuth } from './AuthContext';
import { PresenceState } from '../hooks/usePersonPresence';
import { apiPostJSON, apiPost, API_BASE_URL } from '../utils/api';
import { emitAriaAction, isVoiceOverlayOpen } from '../utils/ariaBus';
import { logEventNow } from '../hooks/useEventLogger';

// "off" disables spoken replies (see playTTS). Anything else = voice on.
const ARIA_VOICE_ENABLED = (process.env.REACT_APP_ARIA_VOICE || 'on').toLowerCase() !== 'off';

const VoiceAgentContext = createContext();

const SPEECH_START_RMS = 0.035;
const SPEECH_STOP_RMS = 0.02;
const SILENCE_STOP_MS = 1200;
const MIN_SPEECH_MS = 300;
const MAX_RECORDING_MS = 15000;

// Dataset page names (docs/dataset/new_actions.json) -> app routes.
const PAGE_ROUTES = {
  home: 'dashboard', dashboard: 'dashboard', body_scanner: 'body-scanner',
  analysis_results: 'analysis-results', recommendations: 'recommendations',
  ai_stylist: 'stylist', stylist: 'stylist', outfit_builder: 'outfit-builder',
  virtual_tryon: 'virtual-tryon', personalization: 'personalization', shopping: 'shopping',
  profile: 'profile', staff_assistance: 'staff-requests', staff_requests: 'staff-requests',
  settings: 'settings',
};
const routeFor = (page) => PAGE_ROUTES[String(page || '').replace(/-/g, '_')] || String(page || 'dashboard');

// Actions a specific screen owns -- forwarded to it over the action bus.
const PAGE_ACTIONS = {
  set_category_filter: null, set_occasion_filter: null, clear_filters: null, set_department: 'recommendations',
  set_include_filter: 'recommendations', expand_explanation: 'recommendations',
  search: 'shopping', clear_search: 'shopping', show_liked: 'shopping',
  set_lighting: 'virtual-tryon', flip_camera: 'virtual-tryon', capture_photo: 'virtual-tryon',
  retake_photo: 'virtual-tryon', dismiss_photo: 'virtual-tryon', set_tryon_zoom: 'virtual-tryon',
  paginate: null, load_more: null,
};

// Whatever actually scrolls: MainLayout's <main class="page-content"> on
// layouts where it has its own scrollbar, otherwise the page itself.
// Depends on screen width (on some layouts it's <body>), so walk up from the
// content area to the first element that really scrolls.
const scrollArea = () => {
  for (let el = document.querySelector('.page-content'); el; el = el.parentElement) {
    const canScroll = ['auto', 'scroll'].includes(getComputedStyle(el).overflowY)
      || el === document.scrollingElement;
    if (canScroll && el.scrollHeight > el.clientHeight + 4) return el;
  }
  return document.scrollingElement || document.documentElement;
};
const SCROLL_AMOUNTS = { small: 0.25, medium: 0.6, large: 1.5, page: 1.0 };

export function VoiceAgentProvider({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    sessionId, setPendingRecommendations, setHighlightedItemId, highlightedItemId,
    addToCart, removeFromCart, setCartQuantity, clearCart, setCartOpen, cart,
    liked, likeItem, unlikeItem, clearLiked, registerItems, screenItems, getItem,
    tryonItem, setTryonItem,
    queueOutfitActions, showToast, presenceState,
    conversationGreeting, registerVoiceCallbacks,
  } = useSession();
  const { theme, toggleTheme } = useTheme();
  // "Mute your voice" -- replies still appear as text on screen.
  const voiceMutedRef = useRef(false);
  // "Talk slower" / "speak louder".
  const speechRateRef = useRef(1);
  const voiceVolumeRef = useRef(1);
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
    if (ARIA_VOICE_ENABLED === false || voiceMutedRef.current) return;
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
      audio.playbackRate = speechRateRef.current;
      audio.volume = voiceVolumeRef.current;
      currentAudioRef.current = audio;
      audio.onended = () => { setIsSpeaking(false); URL.revokeObjectURL(url); currentAudioRef.current = null; };
      audio.onerror = () => { setIsSpeaking(false); URL.revokeObjectURL(url); currentAudioRef.current = null; };
      audio.play();
    } catch {
      setIsSpeaking(false);
    }
  }, []);

  const handleActions = useCallback(async (actions) => {
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
      const p = action.payload || {};
      if (action.type in PAGE_ACTIONS) {
        // Page-owned action: open the owning screen if needed, then hand it over.
        const owner = PAGE_ACTIONS[action.type];
        if (owner && location.pathname !== `/${owner}`) navigate(`/${owner}`);
        emitAriaAction(action);
        continue;
      }
      switch (action.type) {
        case 'navigate':
          navigate(`/${routeFor(p.page)}`);
          break;
        case 'go_back':
          if (isVoiceOverlayOpen()) emitAriaAction({ type: 'close_item_detail', payload: {} });
          else navigate(-1);
          break;
        case 'go_forward':
          navigate(1);
          break;
        case 'scroll': {
          const el = scrollArea();
          const step = window.innerHeight * (SCROLL_AMOUNTS[p.amount] || SCROLL_AMOUNTS.medium);
          el.scrollBy({ top: p.direction === 'up' ? -step : step, behavior: 'smooth' });
          break;
        }
        case 'scroll_to': {
          const el = scrollArea();
          el.scrollTo({ top: p.position === 'bottom' ? el.scrollHeight : 0, behavior: 'smooth' });
          break;
        }
        case 'stop_speaking':
          if (currentAudioRef.current) {
            currentAudioRef.current.pause();
            currentAudioRef.current = null;
          }
          setIsSpeaking(false);
          break;
        case 'set_voice_mute':
          voiceMutedRef.current = !!p.muted;
          if (p.muted && currentAudioRef.current) {
            currentAudioRef.current.pause();
            currentAudioRef.current = null;
            setIsSpeaking(false);
          }
          break;
        case 'set_speech_rate':
          speechRateRef.current = { slow: 0.85, normal: 1, fast: 1.2 }[p.rate] || 1;
          break;
        case 'set_voice_volume':
          voiceVolumeRef.current = Math.min(1, Math.max(0.2,
            p.level != null ? Number(p.level) : voiceVolumeRef.current + (p.change === 'down' ? -0.25 : 0.25)));
          if (currentAudioRef.current) currentAudioRef.current.volume = voiceVolumeRef.current;
          break;
        case 'rate_item':
          logEventNow(sessionId, p.item_id, p.thumb === 'down' ? 'dismiss' : 'click', {
            source: 'voice', action: 'rate', stars: p.stars ?? null, thumb: p.thumb ?? null,
          });
          showToast(p.stars ? `Rated ${p.stars} star${p.stars === 1 ? '' : 's'}` : 'Thanks for the feedback', 'success');
          break;
        case 'reserve_item':
          logEventNow(sessionId, p.item_id, 'click', { source: 'voice', action: 'reserve', size: p.size ?? null });
          showToast('Reserved -- a staff member will keep it aside', 'success');
          break;
        case 'send_to_fitting_room':
          showToast('A staff member will bring your items to a fitting room', 'success');
          break;
        case 'correct_profile_field':
          // "I'm actually 165 cm" / "I'm a size M".
          try {
            const endpoint = p.field === 'height_cm'
              ? '/api/vision/scan/height'
              : p.field === 'body_size_estimate'
                ? '/api/vision/scan/size'
                : null;
            if (endpoint) await apiPostJSON(endpoint, { session_id: sessionId, [p.field]: p.value });
          } catch (err) { console.warn('[voice] profile correction failed', err); }
          showToast(`Updated your ${p.field === 'height_cm' ? 'height' : 'size'}.`, 'success');
          break;
        case 'read_scan_status':
          emitAriaAction(action);  // Body Scanner / Profile pages show the status
          showToast('Here\'s what we have from your scan.', 'info');
          break;
        case 'set_captions':
          try { localStorage.setItem('mirrorai-captions', p.enabled ? '1' : '0'); } catch { /* storage blocked */ }
          emitAriaAction(action);
          break;
        case 'undo_last_action':
          emitAriaAction(action);
          showToast('Undone', 'info');
          break;
        case 'zoom_item_image':
        case 'compare_items':
        case 'close_item_detail':
          emitAriaAction(action);   // MainLayout shows the enlarged / side-by-side view
          break;
        case 'set_theme':
          if (p.mode && p.mode !== theme) toggleTheme();
          break;
        case 'set_hands_free':
          setHandsFreeMode(!!p.enabled);
          break;
        case 'toggle_sidebar':
        case 'set_aria_panel':
        case 'show_confirmation':
        case 'hide_confirmation':
        case 'show_help':
          emitAriaAction(action);   // MainLayout / AriaOverlay render these
          break;
        case 'focus_item':
          setHighlightedItemId(p.item_id || null);
          emitAriaAction(action);   // the open list scrolls the card into view
          break;
        case 'like_item':
          likeItem(p.item || p.item_id);
          showToast('Added to your favourites', 'success');
          break;
        case 'unlike_item':
          unlikeItem(p.item_id);
          showToast('Removed from favourites', 'info');
          break;
        case 'clear_liked':
          clearLiked();
          break;
        case 'open_cart':
          if (location.pathname !== '/shopping') navigate('/shopping');
          setCartOpen(true);
          break;
        case 'close_cart':
          setCartOpen(false);
          break;
        case 'remove_from_cart':
          removeFromCart(p.item_id);
          setCartOpen(true);
          break;
        case 'set_cart_quantity':
          setCartQuantity(p.item_id, { quantity: p.quantity, delta: p.delta });
          setCartOpen(true);
          break;
        case 'clear_cart':
          clearCart();
          break;
        case 'read_cart_summary':
          setCartOpen(true);
          break;
        case 'start_scan':
          navigate('/body-scanner');
          break;
        case 'show_recommendations':
          // Whole payload: {results, sections?} -- sections present for the
          // post-scan complete look (see Recommendations.js).
          registerItems(action.payload?.results || []);
          setPendingRecommendations({
            results: action.payload?.results || [],
            sections: action.payload?.sections || null,
          });
          navigate('/recommendations');
          break;
        case 'show_item':
          setHighlightedItemId(action.payload?.item_id || null);
          if (!['/recommendations', '/shopping'].includes(location.pathname)) navigate('/recommendations');
          emitAriaAction({ type: 'focus_item', payload: action.payload });
          break;
        case 'add_to_cart':
          addToCart(action.payload?.item || action.payload?.item_id);
          showToast('Added to your fitting room', 'success');
          break;
        case 'add_to_wardrobe':
          try { await apiPostJSON('/api/wardrobe/add', { session_id: sessionId, item_id: p.item_id }); }
          catch (err) { console.warn('[voice] wardrobe add failed', err); }
          showToast('Saved to your wardrobe', 'success');
          break;
        case 'show_wardrobe':
          navigate('/personalization');
          showToast('Showing your wardrobe', 'info');
          break;
        case 'suggest_from_wardrobe':
          try {
            const data = await apiPostJSON(`/api/wardrobe/${sessionId}/complete`, {});
            if (data?.results?.length) {
              setPendingRecommendations({ results: data.results, sections: null });
              navigate('/recommendations');
            } else {
              showToast('Save some items to your wardrobe first', 'info');
            }
          } catch (err) { showToast('Could not match wardrobe', 'error'); }
          break;
        case 'start_tryon': {
          // Resolve the id to an item (so TryOnMirror has image + category),
          // then open the page. The page reads it from SessionContext.
          const item = action.payload?.item || getItem(action.payload?.item_id);
          setTryonItem(item || null);
          navigate('/virtual-tryon');
          break;
        }
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
        case 'end_conversation':
          // "Thanks" -- let her goodbye play out, then clear the chat and
          // return to the home screen, ready for the next request.
          setTimeout(() => {
            setMessages([]);
            navigate('/dashboard');
          }, 7000);
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
  }, [navigate, location.pathname, setPendingRecommendations, setHighlightedItemId, addToCart, removeFromCart,
      setCartQuantity, clearCart, setCartOpen, likeItem, unlikeItem, clearLiked, registerItems,
      queueOutfitActions, showToast, theme, toggleTheme, logout, sessionId]);

  // What's on the customer's screen, sent with every message so Aria can
  // resolve "remove the second item from my cart", "this one", cart totals
  // and which page's filter to change.
  const clientStateRef = useRef({});
  clientStateRef.current = {
    page: location.pathname.replace(/^\//, '') || 'dashboard',
    highlighted_item_id: highlightedItemId || null,
    cart: (cart || []).map((i) => ({ id: String(i.id), name: i.name, price: i.price || 0, quantity: i.quantity })),
    liked: Object.values(liked || {}).map((i) => ({ id: String(i.id), name: i.name })),
    screen_items: (screenItems || []).slice(0, 60),
  };

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
        body: JSON.stringify({ session_id: sessionId, message: text.trim(), client_state: clientStateRef.current }),
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

      // Silent actions ("stop talking") have no reply -- drop the empty bubble.
      if (!finalReply) setMessages(prev => prev.filter(m => m.id !== aiMsgId));
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
