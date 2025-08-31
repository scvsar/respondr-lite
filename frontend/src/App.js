import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import "./App.css";
import "./Dashboard.geocities.css";
import Logout from './Logout';
import MobileView from './MobileView';
import Profile from './Profile';
import StatusTabs from './StatusTabs';
import WebhookDebug from './WebhookDebug';
import LoginChoice from './LoginChoice';
import AdminPanel from './AdminPanel';

// Simple auth gate: ensures user is authenticated and from an allowed domain
function AuthGate({ children }) {
  const [user, setUser] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [denied, setDenied] = React.useState(null);
  const loc = useLocation();

  const signInUrl = React.useCallback((path) => {
    const rd = encodeURIComponent(path || '/');
    // If we're on port 3100 (CRA dev) and backend is on 8000, send user to backend's oauth start
    const host = typeof window !== 'undefined' ? window.location.host : '';
    const isDevPort = host.endsWith(':3100');
    if (isDevPort) {
      return `http://localhost:8000/oauth2/start?rd=${rd}`;
    }
    return `/.auth/login/aad?post_login_redirect_uri=${rd}`;
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch('/api/user');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (cancelled) return;
        setUser(j);
        if (!j.authenticated) {
          // Not authenticated: show Sign In option instead of auto-redirect (handles when EasyAuth is disabled)
          setDenied({ error: 'Not authenticated' });
          return;
        }
        if (j.error === 'Access denied') {
          setDenied(j);
        }
      } catch (e) {
        if (!cancelled) setDenied({ error: 'Unable to verify sign-in' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [loc.pathname, signInUrl]);

  if (loading) return <div className="empty">Checking sign-in…</div>;
  if (denied) {
    // Show login choice page instead of simple sign-in button
    return <LoginChoice />;
  }
  return children;
}

// Admin gate: ensures user is authenticated and has admin privileges
function AdminGate({ children }) {
  const [user, setUser] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [denied, setDenied] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const resp = await fetch("/api/user", { credentials: 'include' });
        if (!resp.ok) {
          if (!cancelled) {
            setDenied("Failed to load user info");
            setLoading(false);
          }
          return;
        }
        const userData = await resp.json();
        if (!cancelled) {
          if (!userData.authenticated) {
            setDenied("Authentication required");
          } else if (!userData.is_admin) {
            setDenied("Admin privileges required");
          } else {
            setUser(userData);
          }
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setDenied("Network error loading user info");
          setLoading(false);
        }
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div style={{ padding: '40px', textAlign: 'center', color: '#a0a0a0' }}>Loading...</div>;
  }

  if (denied) {
    return (
      <div style={{ 
        padding: '40px', 
        textAlign: 'center', 
        color: '#ff6b6b',
        background: '#1a1a1a',
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column'
      }}>
        <h2 style={{ color: '#ffffff', marginBottom: '16px' }}>Access Denied</h2>
        <p style={{ marginBottom: '24px' }}>{denied}</p>
        <button 
          onClick={() => window.location.href = '/'}
          style={{
            background: '#0078d4',
            color: 'white',
            border: 'none',
            padding: '12px 24px',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          Return to Dashboard
        </button>
      </div>
    );
  }

  return children;
}

function MainApp() {
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [vehicleFilter, setVehicleFilter] = useState([]); // e.g., ["POV","SAR-7"]
  // Defaults: All Messages tab should start with filters cleared; Current Status shows Responding by default
  const [statusFilter, setStatusFilter] = useState([]); // ["Responding","Not Responding","Unknown"]
  const [activeTab, setActiveTab] = useState('all');
  const [geocitiesMode, setGeocitiesMode] = useState(() => {
    // Always start disabled by default for professional appearance
    // Users must explicitly enable the retro mode each session
    return false;
  });
  const [geocitiesConfig, setGeocitiesConfig] = useState({ force_mode: false, enable_toggle: false });
  
  // Inactivity detection state
  const INACTIVITY_TIMEOUT = parseInt(process.env.REACT_APP_INACTIVITY_MINUTES || '10') * 60 * 1000; // Default 10 minutes
  const [isInactive, setIsInactive] = useState(false);
  const [lastActivity, setLastActivity] = useState(Date.now());
  const inactivityTimerRef = useRef(null);

  // Fetch configuration on component mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const response = await fetch('/api/config');
        if (response.ok) {
          const config = await response.json();
          setGeocitiesConfig(config.geocities || { force_mode: false, enable_toggle: false });
          // If force mode is enabled, automatically enable GeoCities mode
          if (config.geocities?.force_mode) {
            setGeocitiesMode(true);
          }
        }
      } catch (error) {
        console.warn('Failed to fetch configuration:', error);
      }
    };
    fetchConfig();
  }, []);

  // Toggle GeoCities theme (session-only, resets on page refresh)
  const toggleGeocitiesTheme = useCallback(() => {
    setGeocitiesMode(prev => !prev);
  }, []);

  const handleTabChange = useCallback((tab) => {
    setActiveTab(tab);
    if (tab === 'current') {
      setStatusFilter(['Responding']);
    } else if (tab === 'all') {
  setStatusFilter([]);
  setVehicleFilter([]);
    }
  }, []);
  const [live, setLive] = useState(true);
  const [autoPaused, setAutoPaused] = useState(false); // Track if paused due to inactivity
  const [useUTC, setUseUTC] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [user, setUser] = useState(null);
  const isAdmin = Boolean(user && user.is_admin);
  // popover removed
  const [editMode, setEditMode] = useState(false);
  const [selected, setSelected] = useState(()=>new Set());
  const [showEditor, setShowEditor] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [form, setForm] = useState({
    name: '',
    team: '',
    group_id: '',
    text: '',
    vehicle: '',
    timestamp: '', // datetime-local string
    eta: '',       // free text HH:MM or words
    eta_timestamp: '', // datetime-local string
  });

  // Track user activity
  const handleUserActivity = useCallback(() => {
    setLastActivity(Date.now());
    if (isInactive) {
      setIsInactive(false);
      setAutoPaused(false);
      // Resume live updates if they were on before
      if (live) {
        console.log('Resuming live updates after user activity');
      }
    }
  }, [isInactive, live]);

  // Set up activity listeners
  useEffect(() => {
    const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
    events.forEach(event => {
      document.addEventListener(event, handleUserActivity);
    });
    
    return () => {
      events.forEach(event => {
        document.removeEventListener(event, handleUserActivity);
      });
    };
  }, [handleUserActivity]);

  // Monitor for inactivity
  useEffect(() => {
    const checkInactivity = () => {
      const timeSinceActivity = Date.now() - lastActivity;
      if (timeSinceActivity >= INACTIVITY_TIMEOUT && !isInactive && live) {
        console.log(`No activity for ${INACTIVITY_TIMEOUT / 60000} minutes, pausing live updates`);
        setIsInactive(true);
        setAutoPaused(true);
      }
    };

    // Check every 30 seconds
    const intervalId = setInterval(checkInactivity, 30000);
    
    return () => clearInterval(intervalId);
  }, [lastActivity, isInactive, live, INACTIVITY_TIMEOUT]);

  const fetchData = useCallback(async () => {
    try {
      // Don't fetch data if user just logged out
      if (sessionStorage.getItem('loggedOut')) {
        return;
      }
      // Also don't fetch data if unauthenticated
      try {
        const ur = await fetch('/api/user');
        if (!ur.ok) throw new Error('auth');
        const uj = await ur.json();
        if (!uj.authenticated || uj.error === 'Access denied') {
          setIsLoading(false);
          setData([]);
          return;
        }
      } catch {}
      
      setError(null);
      const res = await fetch("/api/responders", { headers: { 'Accept': 'application/json' }});
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      const json = await res.json();
      setData(json);
      setIsLoading(false);
      setLastUpdated(new Date());
    } catch (err) {
      console.error("Failed to fetch responder data:", err);
      setError(err.message);
      setIsLoading(false);
    }
  }, []);

  // Initial load + Live-controlled polling
  const firstLoadRef = useRef(true);
  useEffect(() => {
    // Don't fetch data if user just logged out
    if (sessionStorage.getItem('loggedOut')) {
      setIsLoading(false);
      return;
    }

    // Only auto-fetch on initial mount
    if (firstLoadRef.current) {
      firstLoadRef.current = false;
      fetchData();
    }

    // If Live is off or auto-paused due to inactivity, do not schedule polling
    if (!live || autoPaused) {
      return;
    }

    // Polling with backoff and live toggle
    let pollInterval = 15000; // 15s default
    const maxInterval = 60000; // Max 60 seconds
    let currentTimeoutId = null;
    let isCancelled = false;

    const pollData = () => {
      if (isCancelled) return;
      
      // Don't schedule polling if auto-paused
      if (autoPaused) return;

      currentTimeoutId = setTimeout(async () => {
        if (isCancelled) return;
        
        // Double-check we're not paused before fetching
        if (autoPaused) return;

        try {
          await fetchData();
          pollInterval = 15000; // Reset on success
        } catch (err) {
          // Exponential backoff on error
          pollInterval = Math.min(pollInterval * 2, maxInterval);
        }

        if (!isCancelled && live && !autoPaused) {
          pollData(); // Schedule next poll only if still Live and not paused
        }
      }, pollInterval);
    };

    // Only start polling if not auto-paused
    if (!autoPaused) {
      pollData();
    }

    return () => {
      isCancelled = true;
      if (currentTimeoutId) {
        clearTimeout(currentTimeoutId);
      }
    };
  }, [fetchData, live, autoPaused]);

  // User info (for avatar initials)
  useEffect(() => {
    const loadUser = async () => {
      try {
        const r = await fetch('/api/user');
        if (r.ok) setUser(await r.json());
      } catch {}
    };
    loadUser();
  }, []);

  const totalMessages = data.length;

  const avgMinutes = () => {
    const times = data
      .map((entry) => entry.minutes_until_arrival)
      .filter((x) => typeof x === "number" && x > 0);

    if (times.length === 0) return "N/A";
    const avg = times.reduce((a, b) => a + b, 0) / times.length;
    return `${Math.round(avg)} minutes`;
  };

  // Derived helpers
  const initials = (user?.email || user?.name || 'U').split('@')[0].split('.').map(s=>s[0]).join('').slice(0,2).toUpperCase();
  const statusOf = (entry) => {
    // Use arrival_status from backend if available, otherwise fall back to vehicle-based logic
    if (entry.arrival_status) {
      if (entry.arrival_status === 'Not Responding') return 'Not Responding';
      if (entry.arrival_status === 'Cancelled') return 'Cancelled';
      if (entry.arrival_status === 'Available') return 'Available';
  if (entry.arrival_status === 'Responding') return 'Responding';
      if (entry.arrival_status === 'Informational') return 'Informational';
      if (entry.arrival_status === 'Unknown') return 'Unknown';
      if (entry.arrival_status === 'On Route') return 'Responding';
      if (entry.arrival_status === 'Arrived') return 'Responding';
      if (entry.arrival_status === 'ETA Format Unknown') return 'Unknown';
      if (entry.arrival_status === 'ETA Parse Error') return 'Unknown';
    }
    
    // Fallback to vehicle-based logic for backward compatibility
    const v = (entry.vehicle || '').toLowerCase();
    if (v === 'not responding') return 'Not Responding';
    if (!v || v === 'unknown') return 'Unknown';
    return 'Responding';
  };
  const vehicleMap = (v) => {
    if (!v) return 'Unknown';
    const s = v.toUpperCase().replace(/\s+/g,'');
    if (s.includes('POV')) return 'POV';
    const m = s.match(/SAR[- ]?(\d+)/);
    return m ? `SAR-${m[1]}` : (s === 'NOTRESPONDING' ? 'Not Responding' : (s === 'UNKNOWN' ? 'Unknown' : v));
  };
  // Resolve a user's vehicle for a given message by falling back to the most recent prior known vehicle
  const getUserId = (entry) => entry.user_id || entry.name || entry.id;
  const resolveVehicle = useCallback((entry) => {
    const v0 = vehicleMap(entry.vehicle);
    // If this message already has a clear vehicle, use it
    if (v0 && v0 !== 'Unknown' && v0 !== 'Not Responding') return v0;
    const uid = getUserId(entry);
    if (!uid) return v0 || 'Unknown';
    const ts = parseTs(entry.timestamp)?.getTime() || Number.MAX_SAFE_INTEGER;
    let bestV = null;
    let bestT = -1;
    for (const m of data) {
      const mid = getUserId(m);
      if (mid !== uid) continue;
      const mv = vehicleMap(m.vehicle);
      if (!mv || mv === 'Unknown' || mv === 'Not Responding') continue;
      const mt = parseTs(m.timestamp)?.getTime() || 0;
      // Only consider prior or equal timestamps to avoid future-leak
      if (mt <= ts && mt > bestT) { bestT = mt; bestV = mv; }
    }
    return bestV || v0 || 'Unknown';
  }, [data]);
  // Fallback mapping for older messages without `team`
  const GROUP_ID_TO_UNIT = {
    "102193274": "OSU Test group",
    "97608845": "SCVSAR 4X4 Team",
    "6846970": "ASAR MEMBERS",
    "61402638": "ASAR Social",
    "19723040": "Snohomish Unit Mission Response",
    "96018206": "SCVSAR-IMT",
    "1596896": "SCVSAR K9 Team",
    "92390332": "ASAR Drivers",
    "99606944": "OSU - Social",
    "14533239": "MSAR Mission Response",
    "106549466": "ESAR Coordination",
    "16649586": "OSU-MISSION RESPONSE",
  };
  const unitOf = (entry) => entry.team || GROUP_ID_TO_UNIT[String(entry.group_id||"") ] || 'Unknown';
  // Timestamp helpers
  const parseTs = (ts) => {
    if (!ts) return null;
    // Support both ISO strings and "YYYY-MM-DD HH:mm:ss" (testing mode)
    const s = typeof ts === 'string' && ts.includes(' ') && !ts.includes('T') ? ts.replace(' ', 'T') : ts;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  };
  const pad2 = (n) => String(n).padStart(2, '0');
  
  // Format timestamp with timezone awareness
  const formatTimestampDirect = (isoString, isUtc = false) => {
    if (!isoString) return '—';
    try {
      const d = parseTs(isoString);
      if (!d) return '—';
      
      if (isUtc) {
        // Display UTC time
        const y = d.getUTCFullYear();
        const M = d.getUTCMonth() + 1;
        const D = d.getUTCDate();
        const h = d.getUTCHours();
        const m = d.getUTCMinutes();
        const s = d.getUTCSeconds();
        return `${pad2(M)}/${pad2(D)}/${y} ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
      } else {
        // Display local time
        const y = d.getFullYear();
        const M = d.getMonth() + 1;
        const D = d.getDate();
        const h = d.getHours();
        const m = d.getMinutes();
        const s = d.getSeconds();
        return `${pad2(M)}/${pad2(D)}/${y} ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
      }
    } catch {
      return '—';
    }
  };
  
  const formatDateTime = (d, utc=false) => {
    if (!d) return '—';
    if (utc) {
      const y = d.getUTCFullYear();
      const M = d.getUTCMonth() + 1;
      const D = d.getUTCDate();
      const h = d.getUTCHours();
      const m = d.getUTCMinutes();
      const s = d.getUTCSeconds();
      return `${pad2(M)}/${pad2(D)}/${y} ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
    }
    // When useUTC is false, display times in local timezone
    // The backend already provides timestamps in the correct timezone (PST/PDT)
    // so we should use the local interpretation without additional timezone conversion
    const y = d.getFullYear();
    const M = d.getMonth() + 1;
    const D = d.getDate();
    const h = d.getHours();
    const m = d.getMinutes();
    const s = d.getSeconds();
    return `${pad2(M)}/${pad2(D)}/${y} ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
  };
  const computeEtaMillis = (entry) => {
    try {
      if (entry.eta_timestamp) {
        const d = parseTs(entry.eta_timestamp);
        if (d) return d.getTime();
      }
      const eta = entry.eta || '';
      const m = eta.match(/^\d{1,2}:\d{2}$/);
      const base = parseTs(entry.timestamp);
      if (m && base) {
        const [hh, mm] = eta.split(':').map(Number);
        // Create ETA timestamp using the same timezone context as the base timestamp
        // Since the backend already provides times in the correct timezone,
        // we use the base timestamp's date and apply the ETA time
        const dt = new Date(base.getTime());
        dt.setHours(hh, mm, 0, 0);
        // If the ETA time is earlier than the message time, assume it's for the next day
        if (dt.getTime() <= base.getTime()) {
          dt.setDate(dt.getDate() + 1);
        }
        return dt.getTime();
      }
    } catch {}
    return NaN;
  };

  // Live-updating elapsed string for lastUpdated
  const [nowTick, setNowTick] = useState(Date.now());
  useEffect(() => {
    // Only tick the "updated ago" timer when Live is on to avoid periodic UI changes
    if (!live) return;
    const id = setInterval(() => setNowTick(Date.now()), 30000); // update every 30s
    return () => clearInterval(id);
  }, [live]);
  const updatedAgo = useMemo(() => {
    if (!lastUpdated) return '—';
    const diffMs = Date.now() - lastUpdated.getTime();
    const sec = Math.floor(diffMs / 1000);
    if (sec < 60) return 'Just now';
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hrs = Math.floor(min / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  }, [lastUpdated, nowTick]);
  const etaDisplay = (entry, utcFlag = useUTC) => {
    if (!entry) return 'Unknown';
    
    // Always use UTC timestamp from backend and convert based on useUTC setting
    const utcTimestamp = entry.eta_timestamp_utc;
    
    if (utcTimestamp) {
      // Convert UTC timestamp to appropriate display format
      return formatTimestampDirect(utcTimestamp, utcFlag);
    }
    
    // Fallback to raw ETA string if no timestamp
    return entry.eta || 'Unknown';
  };

  // Determine if we are in unfiltered mode (show all messages including duplicates)
  const isUnfiltered = useMemo(() => {
    return (vehicleFilter.length === 0) && (statusFilter.length === 0) && (query.trim() === '');
  }, [vehicleFilter, statusFilter, query]);

  // Apply message-level filters using resolved vehicle and computed status
  const filteredMessagesFlat = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.filter(r => {
      const rv = resolveVehicle(r);
      const matchesQuery = !q || [r.name, r.text, rv].some(x => (String(x||'')).toLowerCase().includes(q));
      const vOK = vehicleFilter.length === 0 || vehicleFilter.includes(rv);
      const sOK = statusFilter.length === 0 || statusFilter.includes(statusOf(r));
      return matchesQuery && vOK && sOK;
    });
  }, [data, query, vehicleFilter, statusFilter, resolveVehicle]);

  // Show all matching messages (no deduplication) in All Messages view
  const viewData = useMemo(() => {
    // When no filters, this is equivalent to data; with filters, include all matching rows (no per-user collapse)
    return [...filteredMessagesFlat];
  }, [filteredMessagesFlat]);

  // Filtering and sorting
  const filtered = useMemo(() => viewData, [viewData]);
  const [sortBy, setSortBy] = useState({ key: 'timestamp', dir: 'desc' });
  const totalUniqueResponders = useMemo(() => {
    const ids = new Set(data.map(getUserId).filter(Boolean));
    return ids.size;
  }, [data]);
  const filteredUniqueResponders = useMemo(() => {
    const ids = new Set(filtered.map(getUserId).filter(Boolean));
    return ids.size;
  }, [filtered]);
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a,b) => {
      let av, bv;
      if (sortBy.key === 'timestamp') { const ad=parseTs(a.timestamp); const bd=parseTs(b.timestamp); av = ad?ad.getTime():0; bv = bd?bd.getTime():0; }
      else if (sortBy.key === 'eta') { av = computeEtaMillis(a); bv = computeEtaMillis(b); if (isNaN(av)) av = 0; if (isNaN(bv)) bv = 0; }
      else { av = 0; bv = 0; }
      return sortBy.dir === 'asc' ? av - bv : bv - av;
    });
    return arr;
  }, [filtered, sortBy]);

  const avgMinutesVal = () => {
    // Average over unique users using latest message per user to avoid double-counting
    const source = isUnfiltered ? data : filteredMessagesFlat;
    const latest = new Map();
    for (const msg of source) {
      const uid = getUserId(msg); if (!uid) continue;
      const ts = parseTs(msg.timestamp)?.getTime() || 0;
      const prev = latest.get(uid);
      if (!prev || ts > (parseTs(prev.timestamp)?.getTime() || 0)) latest.set(uid, msg);
    }
    const base = Array.from(latest.values());
    // Only include people who are actively responding with positive ETA
    const times = base
      .map(e => e.minutes_until_arrival)
      .filter(x => typeof x === 'number' && x > 0);
    if (!times.length) return null;
    const total = times.reduce((a,b)=>a+b,0);
    return Math.round(total / times.length);
  };
  const avgMin = avgMinutesVal();
  const avgText = avgMin == null ? 'N/A' : `${Math.floor(avgMin/60)}h ${avgMin%60}m`;

  const toggleInArray = (arr, val, setter) => {
    if (arr.includes(val)) setter(arr.filter(x=>x!==val)); else setter([...arr, val]);
  };

  const exportCsv = () => {
    const rows = ['Time,Name,Team,Message,Vehicle,ETA,Status'];
    sorted.forEach(r => {
      // Always use UTC timestamps and convert based on useUTC setting
      const ts = formatTimestampDirect(r.timestamp_utc || r.timestamp, useUTC);
      const etaStr = etaDisplay(r, useUTC);
      const row = [ts, r.name, unitOf(r), (r.text||'').replace(/"/g,'""'), resolveVehicle(r), etaStr, statusOf(r)];
      rows.push(row.map(v => /[",\n]/.test(String(v)) ? '"'+String(v)+'"' : String(v)).join(','));
    });
    const blob = new Blob([rows.join('\n')], {type: 'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'responders.csv'; a.click(); URL.revokeObjectURL(url);
  };

  // Removed clearAll endpoint usage; Edit Mode now supports selective deletion.

  // Helpers for datetime-local
  const toLocalInput = (ts) => {
    if (!ts) return '';
    try {
      // Accept ISO or 'YYYY-MM-DD HH:MM:SS'
      const s = ts.includes('T') ? ts : ts.replace(' ', 'T');
      const d = new Date(s);
      if (isNaN(d.getTime())) return '';
      const y = d.getFullYear();
      const M = pad2(d.getMonth()+1);
      const D = pad2(d.getDate());
      const h = pad2(d.getHours());
      const m = pad2(d.getMinutes());
      return `${y}-${M}-${D}T${h}:${m}`;
    } catch { return ''; }
  };
  const fromLocalInput = (val) => {
    if (!val) return '';
    // Keep seconds as :00 for consistency
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(val)) return `${val}:00`;
    return val;
  };

  const resetForm = (seed = {}) => {
    setForm({
      name: seed.name || '',
      team: seed.team || '',
      group_id: seed.group_id || '',
      text: seed.text || '',
      vehicle: seed.vehicle || '',
      timestamp: toLocalInput(seed.timestamp) || '',
      eta: seed.eta || '',
      eta_timestamp: toLocalInput(seed.eta_timestamp) || '',
    });
  };
  const openAdd = () => {
    if (!isAdmin) return;
    setEditingId(null);
    resetForm({ timestamp: new Date().toISOString() });
    setShowEditor(true);
  };
  const openEdit = () => {
    if (!isAdmin) return;
    if (selected.size !== 1) return;
    const id = Array.from(selected)[0];
    const item = data.find(x => String(x.id) === String(id));
    if (!item) return;
    setEditingId(id);
    resetForm(item);
    setShowEditor(true);
  };
  const saveForm = async () => {
    if (!isAdmin) { alert('Only admins can modify entries.'); return; }
    const payload = {
      name: form.name?.trim() || undefined,
      team: form.team?.trim() || undefined,
      group_id: form.group_id?.trim() || undefined,
      text: form.text ?? '',
      vehicle: form.vehicle?.trim() || undefined,
    };
    if (form.timestamp) payload.timestamp = fromLocalInput(form.timestamp);
    if (form.eta_timestamp) payload.eta_timestamp = fromLocalInput(form.eta_timestamp);
    if (form.eta && !form.eta_timestamp) payload.eta = form.eta;

    const opts = {
      method: editingId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(payload),
    };
    const url = editingId ? `/api/responders/${editingId}` : '/api/responders';
    const r = await fetch(url, opts);
    if (!r.ok) { alert('Save failed'); return; }
    setShowEditor(false);
    setEditingId(null);
    setSelected(new Set());
  setRefreshNonce(n=>n+1);
  await fetchData();
  };
  const deleteSelected = async () => {
    if (!isAdmin) { alert('Only admins can delete entries.'); return; }
    if (!selected.size) return;
    if (!window.confirm(`Delete ${selected.size} entr${selected.size===1?'y':'ies'}?`)) return;
    let ok = true;
    if (selected.size === 1) {
      const id = Array.from(selected)[0];
      const r = await fetch(`/api/responders/${id}`, { method: 'DELETE' });
      ok = r.ok;
    } else {
      const r = await fetch('/api/responders/bulk-delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selected) }),
      });
      ok = r.ok;
    }
    if (!ok) { alert('Delete failed'); return; }
    setSelected(new Set());
  setRefreshNonce(n=>n+1);
  await fetchData();
  };
  const toggleRow = (id) => {
    setSelected(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };
  const toggleAll = () => {
    if (selected.size === sorted.length) setSelected(new Set());
    else setSelected(new Set(sorted.map(x => x.id)));
  };

  // Select/Deselect only the currently visible rows in the active table
  const toggleAllVisible = (ids = []) => {
    if (!Array.isArray(ids)) ids = [];
    const allVisibleSelected = ids.length > 0 && ids.every(id => selected.has(id)) && selected.size === ids.length;
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(ids));
    }
  };

  const sortButton = (label, key) => (
    <button
      className="btn"
      aria-sort={sortBy.key===key ? (sortBy.dir==='asc'?'ascending':'descending') : 'none'}
      onClick={() => setSortBy(s => ({ key, dir: s.key===key && s.dir==='desc' ? 'asc' : 'desc' }))}
      title={`Sort by ${label}`}
    >{label} {sortBy.key===key ? (sortBy.dir==='asc'?'▲':'▼') : ''}</button>
  );

  // Visitor counter (fake but fun!)
  const [visitorCount] = useState(() => Math.floor(Math.random() * 999999) + 100000);

  return (
    <div className={geocitiesMode ? "App geocities-theme" : "App"}>
      {/* GeoCities Mode Enhancements */}
      {geocitiesMode && (
        <>
          {/* Under Construction GIF */}
          <div className="under-construction" title="Under Construction since 1996!" />
          
          {/* Marquee */}
          <div className="geocities-marquee">
            <span className="marquee-text">
              🚨 WELCOME TO THE WORLD WIDE WEB! 🚨 BEST VIEWED IN NETSCAPE NAVIGATOR 3.0 🚨 
              THIS SITE IS UNDER CONSTRUCTION 🔨 PLEASE SIGN MY GUESTBOOK! 📖 
              YOU ARE VISITOR NUMBER {visitorCount}! 🎉 CHECK OUT MY WEBRING! 🔗
            </span>
          </div>
          
          {/* Visitor Counter */}
          <div className="visitor-counter">
            VISITOR COUNTER: {visitorCount.toLocaleString()}
          </div>
          
          {/* Hit Counter */}
          <div className="hit-counter">{Math.floor(Math.random() * 9999999)}</div>
          
          {/* MIDI Player */}
          <div className="midi-player" />
          
          {/* Dancing Baby */}
          <div className="dancing-baby" title="Dancing Baby!" />
        </>
      )}
      
      {/* App Bar */}
      <div className={geocitiesMode ? "app-bar geocities-nav" : "app-bar"}>
        <div className="left">
          <img src="/scvsar-logo.png" alt="SCVSAR" className="logo" onError={(e)=>e.currentTarget.style.display='none'} />
          <div className={geocitiesMode ? "app-title fire-text" : "app-title"}>
            {geocitiesMode ? "🔥 SCVSAR CYBER COMMAND CENTER 🔥" : "SCVSAR Response Tracker"}
          </div>
        </div>
        <div className="center">
          { /* Optional mission title placeholder */ }
          <div className="mission-title" title="Mission/Incident">&nbsp;</div>
        </div>
        <div className="right" style={{position:'relative'}}>
          <div className="avatar" onClick={()=>setMenuOpen(v=>!v)} aria-haspopup="menu" aria-expanded={menuOpen}>{initials}</div>
          {menuOpen && (
            <div className="menu" role="menu">
              {user?.email && <div className="menu-item" aria-disabled>Signed in as {user.email}</div>}
              <div className="menu-item" onClick={()=>window.location.href='/profile'}>Profile</div>
              <div className="menu-item" onClick={()=>{ 
                try { window.localStorage.removeItem('respondr_force_desktop'); } catch {}
                const u = new URL(window.location.origin + '/m');
                u.searchParams.set('mobile','1');
                window.location.href = u.toString();
              }}>Mobile Site</div>
              <div className="menu-item" onClick={async ()=>{ 
                sessionStorage.setItem('respondr_logging_out','true'); 
                const host = window.location.host;
                if (host.endsWith(':3100')) {
                  window.location.href = 'http://localhost:8000/oauth2/sign_out?rd=/oauth2/start?rd=/';
                } else if (user?.auth_type === 'local') {
                  await fetch('/api/auth/local/logout', { method: 'POST', credentials: 'include' });
                  sessionStorage.clear();
                  window.location.reload();
                } else {
                  window.location.href = '/.auth/logout?post_logout_redirect_uri=%2F.auth%2Flogin%2Faad%3Fpost_login_redirect_uri%3D%2F';
                }
              }}>Switch Account</div>
              {isAdmin && (
                <div className="menu-item" onClick={()=>{ window.location.href = '/admin'; }}>Admin Panel</div>
              )}
              {isAdmin && (
                <div className="menu-item" onClick={()=>{ window.location.href = '/debug/webhook'; }}>Webhook Debug</div>
              )}
              {geocitiesConfig.enable_toggle && (
                <div className="menu-item" onClick={toggleGeocitiesTheme}>
                  {geocitiesMode ? '🌐 Disable GeoCities Mode' : '🔥 Enable GeoCities Mode'}
                </div>
              )}
              <div className="menu-item" onClick={async ()=>{ 
                sessionStorage.setItem('respondr_logging_out','true'); 
                const host = window.location.host;
                if (host.endsWith(':3100')) {
                  window.location.href = 'http://localhost:8000/oauth2/sign_out?rd=/';
                } else if (user?.auth_type === 'local') {
                  await fetch('/api/auth/local/logout', { method: 'POST', credentials: 'include' });
                  sessionStorage.clear();
                  window.location.reload();
                } else {
                  const url = user?.logout_url || '/.auth/logout?post_logout_redirect_uri=/';
                  window.location.href = url;
                }
              }}>Logout</div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        {/* Secondary Toolbar */}
        <div className="toolbar">
        <input className="search-input" placeholder="Search name/message/vehicle…" value={query} onChange={e=>setQuery(e.target.value)} />
        <div className="chip-row" aria-label="Quick filters">
          {Array.from(new Set(
            data
              .map(e => resolveVehicle(e))
              // Exclude status-like values from vehicle chips to avoid duplicates
              .filter(v => v && v !== 'Not Responding' && v !== 'Unknown')
          ))
            .sort((a,b)=>String(a).localeCompare(String(b)))
            .map(v => (
              <div key={v} className={"chip "+(vehicleFilter.includes(v)?'active':'')} onClick={()=>toggleInArray(vehicleFilter, v, setVehicleFilter)}>{v}</div>
            ))}
          {["Responding","Available","Informational","Cancelled","Not Responding","Unknown"].map(s => (
            <div key={s} className={"chip "+(statusFilter.includes(s)?'active':'')} onClick={()=>toggleInArray(statusFilter, s, setStatusFilter)}>{s}</div>
          ))}
        </div>
        <div className="controls">
          <label className="toggle">
            <input type="checkbox" checked={live && !autoPaused} onChange={e => {
              setLive(e.target.checked);
              if (e.target.checked) {
                setAutoPaused(false);
                handleUserActivity();
              }
            }} /> 
            Live {autoPaused && <span style={{color: '#ff9800', fontSize: '0.9em'}}>(Paused - Inactive)</span>}
          </label>
          <label className="toggle"><input type="checkbox" checked={useUTC} onChange={e=>setUseUTC(e.target.checked)} /> UTC</label>
          <button className="btn" onClick={()=>fetchData()} title="Refresh now">Refresh</button>
          <button className="btn" onClick={exportCsv} title="Export CSV">Export</button>
          <a href="/deleted-dashboard" className="btn" target="_blank" rel="noopener noreferrer" title="View deleted messages">Deleted</a>
          {/* Clear-all removed; use Edit Mode delete instead */}
          <span style={{width:12}} />
          {isAdmin && (
            <label className="toggle"><input type="checkbox" checked={editMode} onChange={e=>{ setEditMode(e.target.checked); setSelected(new Set()); }} /> Edit</label>
          )}
          {isAdmin && editMode && (
            <>
              <button className="btn primary" onClick={openAdd}>Add</button>
              <button className="btn" onClick={openEdit} disabled={selected.size!==1}>Edit</button>
              <button className="btn" onClick={deleteSelected} disabled={selected.size===0}>Delete</button>
            </>
          )}
        </div>
      </div>

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card-Responders">
          <div className="stat-title">Responders</div>
          <div className="stat-value">{filteredUniqueResponders}/{totalUniqueResponders}</div>
          <div className="stat-sub">Unique users</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">Messages</div>
          <div className="stat-value">{totalMessages}</div>
          <div className="stat-sub">Total messages</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">Avg ETA</div>
          <div className="stat-value">{avgText}</div>
          <div className="stat-sub">Across responders</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">Updated</div>
          <div className="stat-value"><span className="live-dot" aria-hidden />{updatedAgo}</div>
          <div className="stat-sub">{lastUpdated ? lastUpdated.toLocaleTimeString() : 'waiting…'}</div>
        </div>
      </div>

      {/* Status Tabs */}
      <div className="status-tabs-active">
      <StatusTabs
        data={sorted}
        isLoading={isLoading}
        error={error}
        selected={selected}
        editMode={editMode}
        geocitiesMode={geocitiesMode}
        isAdmin={isAdmin}
        sortBy={sortBy}
        setSortBy={setSortBy}
        toggleRow={toggleRow}
        toggleAll={toggleAll}
  toggleAllVisible={toggleAllVisible}
        statusOf={statusOf}
        unitOf={unitOf}
        resolveVehicle={resolveVehicle}
        etaDisplay={etaDisplay}
        formatTimestampDirect={formatTimestampDirect}
        useUTC={useUTC}
        statusFilter={statusFilter}
        vehicleFilter={vehicleFilter}
        query={query}
  refreshNonce={refreshNonce}
        activeTab={activeTab}
        onTabChange={handleTabChange}
      />
      </div>

      {/* GeoCities Webring & Guestbook */}
      {geocitiesMode && (
        <div className="geocities-footer" style={{padding: '40px 20px', textAlign: 'center'}}>
          {/* Awards Section */}
          <div className="awards">
            <div className="award-badge">COOL SITE OF THE DAY</div>
            <div className="award-badge">HOT SITE</div>
            <div className="award-badge">NETSCAPE NOW!</div>
            <div className="award-badge">5 STARS</div>
          </div>
          
          {/* Webring */}
          <div className="webring">
            <div className="webring-title">🕸️ EMERGENCY SERVICES WEBRING 🕸️</div>
            <div style={{margin: '20px 0'}}>
              <button className="geocities-button" onClick={() => alert('Previous site in ring!')}>← PREVIOUS</button>
              <button className="geocities-button" onClick={() => alert('List all sites!')}>LIST SITES</button>
              <button className="geocities-button" onClick={() => alert('Random site!')}>RANDOM</button>
              <button className="geocities-button" onClick={() => alert('Next site in ring!')}>NEXT →</button>
            </div>
          </div>
          
          {/* Guestbook */}
          <div className="guestbook">
            <div className="guestbook-title">📖 PLEASE SIGN MY GUESTBOOK! 📖</div>
            <button className="geocities-button" onClick={() => alert('Thanks for signing my guestbook!')}>
              SIGN GUESTBOOK
            </button>
          </div>
          
          {/* Email Me */}
          <a href="mailto:webmaster@scvsar.geocities.com" className="email-me">
            EMAIL THE WEBMASTER
          </a>
          
          {/* Best Viewed In */}
          <div style={{marginTop: '30px', color: '#ffff00', fontSize: '14px'}}>
            <div>This page is best viewed with</div>
            <div style={{fontSize: '18px', fontWeight: 'bold', animation: 'rainbow 2s linear infinite'}}>
              NETSCAPE NAVIGATOR 3.0 OR HIGHER
            </div>
            <div>at 800x600 resolution</div>
            <div style={{marginTop: '10px', fontSize: '12px'}}>
              © 1996 SCVSAR CYBER COMMAND | All Rights Reserved | Under Construction Since 1996
            </div>
          </div>
        </div>
      )}

      {showEditor && (
        <div className="modal-backdrop" onClick={()=>setShowEditor(false)}>
          <div className="modal" onClick={e=>e.stopPropagation()} role="dialog" aria-modal>
            <div className="modal-title">{editingId ? 'Edit Entry' : 'Add Entry'}</div>
            <div className="form-grid">
              <label>
                <span>Name</span>
                <input className="input" value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} />
              </label>
              <label>
                <span>Unit/Team</span>
                <input className="input" value={form.team} onChange={e=>setForm(f=>({...f,team:e.target.value}))} />
              </label>
              <label>
                <span>Group ID</span>
                <input className="input" value={form.group_id} onChange={e=>setForm(f=>({...f,group_id:e.target.value}))} />
              </label>
              <label className="span-2">
                <span>Message</span>
                <textarea className="input" rows={3} value={form.text} onChange={e=>setForm(f=>({...f,text:e.target.value}))} />
              </label>
              <label>
                <span>Vehicle</span>
                <input className="input" placeholder="SAR-12 | POV | Not Responding" value={form.vehicle} onChange={e=>setForm(f=>({...f,vehicle:e.target.value}))} />
              </label>
              <label>
                <span>Time</span>
                <input className="input" type="datetime-local" value={form.timestamp} onChange={e=>setForm(f=>({...f,timestamp:e.target.value}))} />
              </label>
              <label>
                <span>ETA (text)</span>
                <input className="input" placeholder="HH:MM or '15 minutes'" value={form.eta} onChange={e=>setForm(f=>({...f,eta:e.target.value}))} />
              </label>
              <label>
                <span>ETA time</span>
                <input className="input" type="datetime-local" value={form.eta_timestamp} onChange={e=>setForm(f=>({...f,eta_timestamp:e.target.value}))} />
              </label>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={()=>setShowEditor(false)}>Cancel</button>
              <button className="btn primary" onClick={saveForm}>Save</button>
            </div>
          </div>
        </div>
      )}
      </div> {/* End main-content */}
    </div>
  );
}

function App() {
  const shouldUseMobile = React.useCallback(() => {
    try {
      if (typeof window === 'undefined') return false;
      const params = new URLSearchParams(window.location.search);
      const desktopParam = params.get('desktop');
      const mobileParam = params.get('mobile');
      if (desktopParam === '1' || desktopParam === 'true') {
        try { window.localStorage.setItem('respondr_force_desktop','true'); } catch {}
        return false;
      }
      if (desktopParam === '0' || desktopParam === 'false' || mobileParam === '1' || mobileParam === 'true') {
        try { window.localStorage.removeItem('respondr_force_desktop'); } catch {}
        if (mobileParam === '1' || mobileParam === 'true') return true;
      }
      const forced = (() => { try { return window.localStorage.getItem('respondr_force_desktop') === 'true'; } catch { return false; } })();
      if (forced) return false;
      const mq = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
      return Boolean(mq);
    } catch { return false; }
  }, []);
  
  return (
    <Router>
      <Routes>
  <Route path="/" element={
          shouldUseMobile() ? <Navigate to="/m" replace /> : (
            <AuthGate>
              <MainApp />
            </AuthGate>
          )
  } />
        <Route path="/m" element={
          <AuthGate>
            <MobileView />
          </AuthGate>
        } />
        <Route path="/profile" element={
          <AuthGate>
            <Profile />
          </AuthGate>
        } />
        <Route path="/logout" element={<Logout />} />
        <Route path="/admin" element={<AdminGate><AdminPanel /></AdminGate>} />
        <Route path="/debug/webhook" element={<AuthGate><WebhookDebug /></AuthGate>} />
      </Routes>
    </Router>
  );
}

export default App;
