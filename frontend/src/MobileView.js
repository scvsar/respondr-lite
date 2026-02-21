import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';
import './App.css';
import { apiGet } from './api';
import { msalInstance } from './auth/msalClient';

// Minimal, focused view for mobile: Name, Vehicle, ETA for Responding only
export default function MobileView() {
  const [data, setData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [live, setLive] = useState(true);
  const [timeFilter, setTimeFilter] = useState('24h');
  const [customTimeStart, setCustomTimeStart] = useState('');
  const [inactivityTimeoutMinutes, setInactivityTimeoutMinutes] = useState(10);
  const [isInactive, setIsInactive] = useState(false);
  const [autoPaused, setAutoPaused] = useState(false);
  const [lastActivity, setLastActivity] = useState(Date.now());
  const [authChecked, setAuthChecked] = useState(false);
  const [accessDenied, setAccessDenied] = useState(null);
  const INACTIVITY_TIMEOUT = inactivityTimeoutMinutes * 60 * 1000;

  const parseTs = (ts) => {
    if (!ts) return null;
    const s = typeof ts === 'string' && ts.includes(' ') && !ts.includes('T') ? ts.replace(' ', 'T') : ts;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  };

  const getTimeFilterUrl = useCallback(() => {
    let url = '/api/responders';
    if (timeFilter === 'all') return url;

    const now = new Date();
    let since;
    switch (timeFilter) {
      case '1h':
        since = new Date(now.getTime() - 1 * 60 * 60 * 1000);
        break;
      case '6h':
        since = new Date(now.getTime() - 6 * 60 * 60 * 1000);
        break;
      case '12h':
        since = new Date(now.getTime() - 12 * 60 * 60 * 1000);
        break;
      case '24h':
        since = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        break;
      case '3d':
        since = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
        break;
      case '7d':
        since = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        break;
      case 'custom':
        since = customTimeStart ? parseTs(customTimeStart) : null;
        break;
      default:
        since = null;
        break;
    }

    if (since) {
      url += `?since=${since.toISOString()}`;
    }
    return url;
  }, [timeFilter, customTimeStart]);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      // check auth first
      try {
        const uj = await apiGet('/api/user');
        setAuthChecked(true);
        if (!uj.authenticated || uj.error === 'Access denied') {
          setIsLoading(false);
          setAccessDenied(uj);
          setData([]);
          return;
        }
      } catch {}
      const json = await apiGet(getTimeFilterUrl());
      setData(json);
      setIsLoading(false);
      setLastUpdated(new Date());
    } catch (e) {
      console.error(e);
      setError(String(e.message || e));
      setIsLoading(false);
    }
  }, [getTimeFilterUrl]);

  // Fetch backend configuration (inactivity timeout)
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const config = await apiGet('/api/config');
        if (config?.inactivity?.timeout_minutes) {
          setInactivityTimeoutMinutes(config.inactivity.timeout_minutes);
        }
      } catch {}
    };
    fetchConfig();
  }, []);

  // Track user activity for auto-pause parity with desktop
  const handleUserActivity = useCallback(() => {
    setLastActivity(Date.now());
    if (isInactive) {
      setIsInactive(false);
      setAutoPaused(false);
    }
  }, [isInactive]);

  useEffect(() => {
    const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
    events.forEach(event => document.addEventListener(event, handleUserActivity));
    return () => events.forEach(event => document.removeEventListener(event, handleUserActivity));
  }, [handleUserActivity]);

  useEffect(() => {
    const checkInactivity = () => {
      const idleMs = Date.now() - lastActivity;
      if (idleMs >= INACTIVITY_TIMEOUT && !isInactive && live) {
        setIsInactive(true);
        setAutoPaused(true);
      }
    };
    const intervalId = setInterval(checkInactivity, 30000);
    return () => clearInterval(intervalId);
  }, [lastActivity, INACTIVITY_TIMEOUT, isInactive, live]);

  const firstLoadRef = useRef(true);
  useEffect(() => {
    if (firstLoadRef.current) {
      firstLoadRef.current = false;
      fetchData();
    }
    let id;
    const poll = async () => {
      // If Live is off, don't schedule the next poll
      if (!live || autoPaused) return;
      id = setTimeout(async () => {
        try { await fetchData(); } finally { poll(); }
      }, 15000);
    };
    poll();
    return () => { if (id) clearTimeout(id); };
  }, [fetchData, live, autoPaused]);

  // Refresh immediately when time filter changes
  useEffect(() => {
    if (!firstLoadRef.current) {
      fetchData();
    }
  }, [timeFilter, customTimeStart, fetchData]);

  // Helpers local to this view
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
    const v = (entry.vehicle || '').toLowerCase();
    if (v === 'not responding') return 'Not Responding';
    if (!v || v === 'unknown') return 'Unknown';
    return 'Responding';
  };

  const vehicleMap = (v) => {
    if (!v) return 'Unknown';
    const s = String(v).toUpperCase().replace(/\s+/g, '');
    if (s.includes('POV')) return 'POV';
    const m = s.match(/SAR[- ]?(\d+)/);
    return m ? `SAR-${m[1]}` : (s === 'NOTRESPONDING' ? 'Not Responding' : (s === 'UNKNOWN' ? 'Unknown' : String(v)));
  };
  const getUserId = (e) => e.user_id || e.name || e.id;
  const resolveVehicle = useCallback((entry) => {
    const v0 = vehicleMap(entry.vehicle);
    if (v0 && v0 !== 'Unknown' && v0 !== 'Not Responding') return v0;
    const uid = getUserId(entry);
    if (!uid) return v0 || 'Unknown';
    const ts = parseTs(entry.timestamp)?.getTime() || Number.MAX_SAFE_INTEGER;
    let bestV = null, bestT = -1;
    for (const m of data) {
      const mid = getUserId(m); if (mid !== uid) continue;
      const mv = vehicleMap(m.vehicle);
      if (!mv || mv === 'Unknown' || mv === 'Not Responding') continue;
      const mt = parseTs(m.timestamp)?.getTime() || 0;
      if (mt <= ts && mt > bestT) { bestT = mt; bestV = mv; }
    }
    return bestV || v0 || 'Unknown';
  }, [data]);
  // Fallback mapping for unit display on mobile
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
    "19801892": "Tracker Team",
  };
  const unitOf = (entry) => entry.team || GROUP_ID_TO_UNIT[String(entry.group_id||"") ] || 'Unknown';

  const pad2 = (n) => String(n).padStart(2, '0');
  const formatTimestampDirect = (isoString) => {
    if (!isoString) return '—';
    try {
      if (typeof isoString === 'string' && isoString.includes('T')) {
        const match = isoString.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
        if (match) {
          const [, y, M, D, h, m, s] = match;
          return `${M}/${D}/${y} ${h}:${m}:${s}`;
        }
      }
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return '—';
      return `${pad2(d.getMonth()+1)}/${pad2(d.getDate())}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
    } catch { return '—'; }
  };

  const etaDisplay = (entry) => {
    if (!entry) return 'Unknown';
    if (entry.eta_timestamp) return formatTimestampDirect(entry.eta_timestamp);
    return entry.eta || 'Unknown';
  };

  // Filter to Responding only
  const responding = useMemo(() => data.filter((e) => statusOf(e) === 'Responding'), [data]);

  // Dedupe by user_id keeping latest message per user among Responding
  const deduped = useMemo(() => {
    const latest = new Map();
    responding.forEach(msg => {
      const uid = getUserId(msg);
      if (!uid) return;
      const ts = parseTs(msg.timestamp)?.getTime() || 0;
      const prev = latest.get(uid);
      if (!prev || ts > (parseTs(prev.timestamp)?.getTime() || 0)) {
        latest.set(uid, msg);
      }
    });
    return Array.from(latest.values());
  }, [responding]);

  // Sort by most recent message (timestamp) descending
  const sorted = useMemo(() => {
    const arr = [...deduped];
    arr.sort((a,b) => {
      const at = parseTs(a.timestamp)?.getTime() || 0;
      const bt = parseTs(b.timestamp)?.getTime() || 0;
      return bt - at; // newest first
    });
    return arr;
  }, [deduped]);

  // Summary stats
  const totalMessages = data.length;
  const uniqueFilteredResponders = deduped.length;
  const avgMinutes = useMemo(() => {
    const times = deduped.map(e => e.minutes_until_arrival).filter(x => typeof x === 'number' && x > 0);
    if (!times.length) return null;
    const avg = Math.round(times.reduce((a,b)=>a+b,0) / times.length);
    return avg; // minutes
  }, [deduped]);

  const avgText = avgMinutes == null ? 'N/A' : `${avgMinutes}m`;

  return (
    <div className="App">
      <div className="app-bar">
        <div className="left">
          <img src="/scvsar-logo.png" alt="SCVSAR" className="logo" onError={(e)=>e.currentTarget.style.display='none'} />
          <div className="app-title">Responders (Mobile)</div>
        </div>
        <div className="right" style={{marginLeft:'auto'}}>
          {/* Full site button respects View Desktop preference */}
          <button
            className="btn"
            onClick={() => {
              try { window.localStorage.setItem('respondr_force_desktop','true'); } catch {}
              const u = new URL(window.location.origin + '/');
              u.searchParams.set('desktop','1');
              window.location.href = u.toString();
            }}
            title="View Desktop Site"
          >Full Site</button>
        </div>
      </div>

      <div className="mobile-stats">
        <div className="mobile-stat">
          <div className="mobile-stat-label">Messages</div>
          <div className="mobile-stat-value">{totalMessages}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Responders</div>
          <div className="mobile-stat-value">{uniqueFilteredResponders}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Avg ETA</div>
          <div className="mobile-stat-value">{avgText}</div>
        </div>
      </div>

      <div style={{display:'flex', gap:8, alignItems:'center', margin:'8px 12px 12px', flexWrap:'wrap'}}>
        <label style={{fontSize:12, opacity:0.85}}>Window</label>
        <select
          className="btn"
          value={timeFilter}
          onChange={(e) => setTimeFilter(e.target.value)}
          style={{minWidth:96}}
          aria-label="Message time window"
        >
          <option value="1h">1h</option>
          <option value="6h">6h</option>
          <option value="12h">12h</option>
          <option value="24h">24h</option>
          <option value="3d">3d</option>
          <option value="7d">7d</option>
          <option value="all">All</option>
          <option value="custom">Custom</option>
        </select>
        {timeFilter === 'custom' && (
          <input
            type="datetime-local"
            className="btn"
            value={customTimeStart}
            onChange={(e) => setCustomTimeStart(e.target.value)}
            aria-label="Custom start time"
          />
        )}
      </div>

      {error && (
        <div className="empty" role="alert">{error}</div>
      )}
      {authChecked && accessDenied && (
        <div className="empty" role="alert">
          {accessDenied.message || 'Access denied'}
          <div style={{marginTop:12}}>
            <button className="btn" onClick={async () => {
                sessionStorage.setItem('respondr_logging_out','true');
                const local = window.localStorage.getItem("local_jwt");
                if (local) {
                    window.localStorage.removeItem("local_jwt");
                    sessionStorage.clear();
                    window.location.reload();
                } else {
                    await msalInstance.logoutRedirect();
                }
            }}>Sign out</button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="mobile-list">
          {[...Array(6)].map((_,i)=> (
            <div className="mobile-card" key={i}>
              <div className="skeleton" style={{height:18, width:'40%'}} />
              <div className="skeleton" style={{height:14, width:'30%', marginTop:8}} />
              <div className="skeleton" style={{height:14, width:'50%', marginTop:8}} />
            </div>
          ))}
        </div>
      ) : (
        <div className="mobile-list">
          {/* Header indicating the right column is ETA */}
          <div className="mobile-list-header" aria-hidden>
            <div className="mobile-list-header-spacer" />
            <div className="mobile-list-header-eta">ETA</div>
          </div>
          {sorted.length === 0 && (
            <div className="empty">No responders yet.</div>
          )}
      {sorted.map((e, idx) => (
            <div className="mobile-card" key={idx}>
              <div className="mobile-row">
                <div className="mobile-name">{e.name || 'Unknown'}</div>
                <div className="mobile-eta" title={`ETA ${etaDisplay(e)}`}>{etaDisplay(e)}</div>
              </div>
              <div className="mobile-unit">{unitOf(e)}</div>
        <div className="mobile-vehicle">{resolveVehicle(e)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="mobile-footer">
        <span className="live-dot" aria-hidden /> Updated {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : '—'}
        <label className="toggle" style={{marginLeft:12}}>
          <input
            type="checkbox"
            checked={live && !autoPaused}
            onChange={(e) => {
              const next = e.target.checked;
              setLive(next);
              if (next) {
                setIsInactive(false);
                setAutoPaused(false);
                setLastActivity(Date.now());
              }
            }}
          /> Live {autoPaused && <span style={{color:'#ff9800', fontSize:'0.9em'}}>(Paused - Inactive)</span>}
        </label>
      </div>
    </div>
  );
}
