import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RiCustomerService2Line, RiPriceTag3Line, RiBankCardLine, RiRefund2Line,
  RiEmotionUnhappyLine, RiAlertLine, RiQuestionAnswerLine, RiCheckLine,
  RiCheckDoubleLine, RiTimeLine, RiRefreshLine, RiWifiLine, RiWifiOffLine,
} from 'react-icons/ri';
import GlassCard from '../components/Common/GlassCard';
import { useSession } from '../context/SessionContext';
import { apiGetJSON, apiPostJSON, API_BASE_URL } from '../utils/api';
import './StaffRequests.css';

const REASON_META = {
  discount: { label: 'Discount request', icon: <RiPriceTag3Line /> },
  payment: { label: 'Payment / checkout', icon: <RiBankCardLine /> },
  refund: { label: 'Refund', icon: <RiRefund2Line /> },
  complaint: { label: 'Complaint', icon: <RiEmotionUnhappyLine /> },
  stock_issue: { label: 'Stock issue', icon: <RiAlertLine /> },
  special_request: { label: 'Special request', icon: <RiQuestionAnswerLine /> },
  other: { label: 'Other', icon: <RiQuestionAnswerLine /> },
};

const POLL_MS = 30000; // slower fallback poll when WebSocket is connected
const WS_URL = API_BASE_URL.replace(/^http/, 'ws') + '/api/staff/ws';

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function StaffRequests() {
  const { showToast } = useSession();
  const [view, setView] = useState('pending');
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyIds, setBusyIds] = useState(new Set());
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await apiGetJSON(`/api/staff/requests?status=${view}`);
      setRequests(Array.isArray(data) ? data : data?.data ?? []);
    } catch (err) {
      if (!silent) showToast(`Couldn't load staff requests -- ${err.message || 'unknown error'}`, 'error');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [view, showToast]);

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    let ws;
    let reconnectTimer;
    function connect() {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => {
        setWsConnected(false);
        reconnectTimer = setTimeout(connect, 5000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'new_request' && msg.request) {
            setRequests((prev) => [msg.request, ...prev]);
            showToast('New staff request from Aria', 'info');
          } else if (msg.type === 'status_update') {
            load(true);
          }
        } catch { /* ignore malformed */ }
      };
      wsRef.current = ws;
    }
    connect();
    return () => {
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [showToast, load]);

  const setStatus = async (id, status) => {
    setBusyIds((prev) => new Set(prev).add(id));
    try {
      await apiPostJSON(`/api/staff/requests/${id}/status`, { status });
      showToast(
        status === 'resolved' ? 'Marked resolved' : 'Acknowledged',
        'success',
      );
      // Optimistic removal from the pending view; a full reload keeps 'all' in sync.
      if (view === 'pending' && status !== 'pending') {
        setRequests((prev) => prev.filter((r) => r.id !== id));
      } else {
        load(true);
      }
    } catch (err) {
      showToast(`Couldn't update that request -- ${err.message || 'unknown error'}`, 'error');
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const pendingCount = view === 'pending' ? requests.length : requests.filter((r) => r.status === 'pending').length;

  return (
    <div className="staff-requests-page">
      <div className="staff-header">
        <div>
          <h1 className="page-title">
            <RiCustomerService2Line className="title-icon" />
            Staff Assistance
          </h1>
          <p className="page-subtitle">
            Requests Aria has escalated because she isn't authorized to handle them herself.
          </p>
        </div>
        <div className="staff-header-actions">
          {pendingCount > 0 && <span className="pending-badge">{pendingCount} pending</span>}
          <span className={`ws-status ${wsConnected ? 'connected' : ''}`} title={wsConnected ? 'Live updates active' : 'Reconnecting...'}>
            {wsConnected ? <RiWifiLine /> : <RiWifiOffLine />}
          </span>
          <button className="staff-refresh-btn" onClick={() => load()} title="Refresh now">
            <RiRefreshLine />
          </button>
        </div>
      </div>

      <div className="staff-view-toggle">
        <button className={view === 'pending' ? 'active' : ''} onClick={() => setView('pending')}>
          Pending
        </button>
        <button className={view === 'all' ? 'active' : ''} onClick={() => setView('all')}>
          Recent history
        </button>
      </div>

      {loading ? (
        <div className="staff-empty-state">Loading...</div>
      ) : requests.length === 0 ? (
        <div className="staff-empty-state">
          <RiCheckDoubleLine className="empty-icon" />
          <p>{view === 'pending' ? "Nothing pending -- Aria's handling things on her own." : 'No requests yet.'}</p>
        </div>
      ) : (
        <div className="staff-requests-list">
          <AnimatePresence>
            {requests.map((req) => {
              const meta = REASON_META[req.reason] || REASON_META.other;
              const busy = busyIds.has(req.id);
              return (
                <motion.div
                  key={req.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: 40 }}
                  transition={{ duration: 0.3 }}
                >
                  <GlassCard hover={false} className={`staff-request-card status-${req.status}`}>
                    <div className="staff-request-icon">{meta.icon}</div>
                    <div className="staff-request-body">
                      <div className="staff-request-top">
                        <span className="staff-request-reason">{meta.label}</span>
                        <span className="staff-request-time">
                          <RiTimeLine /> {timeAgo(req.created_at)}
                        </span>
                      </div>
                      {req.message && <p className="staff-request-message">"{req.message}"</p>}
                      <span className="staff-request-session">Session {req.session_id?.slice(0, 8)}</span>
                    </div>
                    <div className="staff-request-actions">
                      {req.status === 'pending' && (
                        <>
                          <button
                            className="staff-action-btn ack"
                            disabled={busy}
                            onClick={() => setStatus(req.id, 'acknowledged')}
                          >
                            Acknowledge
                          </button>
                          <button
                            className="staff-action-btn resolve"
                            disabled={busy}
                            onClick={() => setStatus(req.id, 'resolved')}
                          >
                            <RiCheckLine /> Resolve
                          </button>
                        </>
                      )}
                      {req.status === 'acknowledged' && (
                        <button
                          className="staff-action-btn resolve"
                          disabled={busy}
                          onClick={() => setStatus(req.id, 'resolved')}
                        >
                          <RiCheckLine /> Resolve
                        </button>
                      )}
                      {req.status !== 'pending' && (
                        <span className={`status-pill status-${req.status}`}>{req.status}</span>
                      )}
                    </div>
                  </GlassCard>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
