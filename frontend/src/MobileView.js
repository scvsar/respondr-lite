import React, { useCallback, useEffect, useMemo, useState, useRef } from 'react';
import './App.css';
import {timeWindowUrl} from './timeWindow';
import {validateResponderData} from './responderData';
import { apiGet } from './api';
import { responderStatus, vehicleLabel, parseTimestamp, localTimestamp, minutesUntilArrival } from './responderPresentation';
import { msalInstance } from './auth/msalClient';

// Minimal, focused view for mobile: Name, Vehicle, ETA for Responding only
export default function MobileView() {
  const [data, setData] = useState([]);
  const [clockTick, setClockTick] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClockTick(Date.now()), 30000);
    return () => clearInterval(timer);
  }, []);
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

  const getTimeFilterUrl = useCallback(() =>
    timeWindowUrl('/api/current-status', timeFilter, customTimeStart), [timeFilter, customTimeStart]);

  const fetchGeneration = useRef(0);
  useEffect(() => () => { fetchGeneration.current += 1; }, []);
  const fetchData = useCallback(async () => {
    const generation = ++fetchGeneration.current;
    const isCurrent = () => generation === fetchGeneration.current;
    const url = getTimeFilterUrl();
    if (!url) {
      setData([]);
      setIsLoading(false);
      setError('Choose a valid start time.');
      return false;
    }
    setError(null);
    setIsLoading(true);
    try {
      const user = await apiGet('/api/user');
      if (!isCurrent()) return false;
      setAuthChecked(true);
      if (!user.authenticated || user.error === 'Access denied') {
        setAccessDenied(user);
        setData([]);
        setIsLoading(false);
        return false;
      }
      setAccessDenied(null);
      const result = await apiGet(url);
      if (!isCurrent()) return false;
      setData(validateResponderData(result));
      setClockTick(Date.now());
      setLastUpdated(new Date());
      setIsLoading(false);
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      setAuthChecked(true);
      setError(error.message || 'Unable to load responders');
      setData([]);
      setIsLoading(false);
      return false;
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
  const handleUserActivity = useCallback((event) => {
    // Ignore synthetic/non-user events
    if (event && event.isTrusted === false) return;
    setLastActivity(Date.now());
    if (isInactive) {
      setIsInactive(false);
      setAutoPaused(false);
    }
  }, [isInactive]);

  useEffect(() => {
    // Only treat explicit user input as activity.
    // Avoid passive events like mousemove/scroll that can be triggered during auto-refresh.
    const events = ['pointerdown', 'keydown', 'touchstart', 'wheel'];
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

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    if (!live || autoPaused) return;
    let cancelled = false;
    let timer;
    let delay = 15000;
    const poll = () => {
      timer = setTimeout(async () => {
        const success = await fetchData();
        delay = success ? 15000 : Math.min(delay * 2, 60000);
        if (!cancelled) poll();
      }, delay);
    };
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [fetchData, live, autoPaused]);

  const resolveVehicle = entry => vehicleLabel(entry.vehicle);
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

  const etaDisplay = entry => entry.eta_timestamp_utc || entry.eta_timestamp
    ? localTimestamp(entry.eta_timestamp_utc || entry.eta_timestamp) : entry.eta || 'Unknown';
  const deduped = useMemo(() => data.filter(entry => responderStatus(entry) === 'Responding'), [data]);
  const sorted = useMemo(() => [...deduped].sort((a,b) =>
    (parseTimestamp(b.timestamp_utc || b.timestamp)?.getTime() || 0) -
    (parseTimestamp(a.timestamp_utc || a.timestamp)?.getTime() || 0)), [deduped]);

  // Summary stats
  const totalPeople = data.length;
  const uniqueFilteredResponders = deduped.length;
  const avgMinutes = useMemo(() => {
    const times = deduped.map(e => minutesUntilArrival(e, clockTick)).filter(x => typeof x === 'number' && x > 0);
    if (!times.length) return null;
    const avg = Math.round(times.reduce((a,b)=>a+b,0) / times.length);
    return avg; // minutes
  }, [deduped, clockTick]);

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
          <div className="mobile-stat-label">People</div>
          <div className="mobile-stat-value">{error || accessDenied ? '—' : totalPeople}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Responding</div>
          <div className="mobile-stat-value">{error || accessDenied ? '—' : uniqueFilteredResponders}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Avg ETA</div>
          <div className="mobile-stat-value">{error || accessDenied ? 'N/A' : avgText}</div>
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

      {!error && !accessDenied && (isLoading ? (
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
            <div className="mobile-card" key={e.responder_key || e.id || idx}>
              <div className="mobile-row">
                <div className="mobile-name">{e.name || 'Unknown'}</div>
                <div className="mobile-eta" title={`ETA ${etaDisplay(e)}`}>{etaDisplay(e)}</div>
              </div>
              <div className="mobile-unit">{unitOf(e)}</div>
        <div className="mobile-vehicle">{resolveVehicle(e)}</div>
            </div>
          ))}
        </div>
      ))}

      <div className="mobile-footer">
        {live && !autoPaused && !error && !accessDenied && !isLoading && <span className="live-dot" aria-hidden />} {error || accessDenied ? 'Refresh failed. Last updated' : !live || autoPaused ? 'Refresh paused. Last updated' : 'Updated'} {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : '—'}
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
                fetchData();
              }
            }}
          /> Live {autoPaused && <span style={{color:'#ff9800', fontSize:'0.9em'}}>(Paused - Inactive)</span>}
        </label>
      </div>
    </div>
  );
}
