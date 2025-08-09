import React, { useEffect, useState, useCallback, useMemo } from "react";
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import "./App.css";
import Logout from './Logout';
import MobileView from './MobileView';

function MainApp() {
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [vehicleFilter, setVehicleFilter] = useState([]); // e.g., ["POV","SAR-7"]
  const [statusFilter, setStatusFilter] = useState(["Responding"]); // ["Responding","Not Responding","Unknown"]
  const [live, setLive] = useState(true);
  const [useUTC, setUseUTC] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [user, setUser] = useState(null);
  // popover removed

  const fetchData = useCallback(async () => {
    try {
      // Don't fetch data if user just logged out
      if (sessionStorage.getItem('loggedOut')) {
        return;
      }
      
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

  useEffect(() => {
    // Don't fetch data if user just logged out
    if (sessionStorage.getItem('loggedOut')) {
      setIsLoading(false);
      return;
    }

    fetchData();
    
    // Polling with backoff and live toggle
    let pollInterval = 15000; // 15s default
    const maxInterval = 60000; // Max 60 seconds
    let currentTimeoutId = null;
    let isCancelled = false;
    
    const pollData = () => {
      if (isCancelled) return;
      
      currentTimeoutId = setTimeout(async () => {
        if (isCancelled) return;
        
        try {
          if (live) {
            await fetchData();
          }
          pollInterval = 15000; // Reset on success
        } catch (err) {
          // Exponential backoff on error
          pollInterval = Math.min(pollInterval * 2, maxInterval);
        }
        
        if (!isCancelled) {
          pollData(); // Schedule next poll
        }
      }, pollInterval);
    };
    
    pollData();
    
    return () => {
      isCancelled = true;
      if (currentTimeoutId) {
        clearTimeout(currentTimeoutId);
      }
    };
  }, [fetchData]);

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

  const totalResponders = data.length;

  const avgMinutes = () => {
    const times = data
      .map((entry) => entry.minutes_until_arrival)
      .filter((x) => typeof x === "number");

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
  // Timestamp helpers
  const parseTs = (ts) => {
    if (!ts) return null;
    // Support both ISO strings and "YYYY-MM-DD HH:mm:ss" (testing mode)
    const s = typeof ts === 'string' && ts.includes(' ') && !ts.includes('T') ? ts.replace(' ', 'T') : ts;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  };
  const pad2 = (n) => String(n).padStart(2, '0');
  
  // Simple function to format ISO timestamp as MM/DD/YYYY HH:MM:SS preserving original timezone
  const formatTimestampDirect = (isoString) => {
    if (!isoString) return '—';
    try {
      // For PST/PDT timestamps (e.g., "2025-08-09T12:00:00-08:00"), 
      // we want to show the time exactly as it appears in the timestamp
      // without any timezone conversion
      
      if (typeof isoString === 'string' && isoString.includes('T')) {
        // Extract date and time parts directly from the ISO string
        const match = isoString.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
        if (match) {
          const [, year, month, day, hour, minute, second] = match;
          return `${month}/${day}/${year} ${hour}:${minute}:${second}`;
        }
      }
      
      // Fallback to Date parsing if string format doesn't match
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return '—';
      
      const M = d.getMonth() + 1;
      const D = d.getDate();
      const y = d.getFullYear();
      const h = d.getHours();
      const m = d.getMinutes();
      const s = d.getSeconds();
      return `${pad2(M)}/${pad2(D)}/${y} ${pad2(h)}:${pad2(m)}:${pad2(s)}`;
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
    const id = setInterval(() => setNowTick(Date.now()), 30000); // update every 30s
    return () => clearInterval(id);
  }, []);
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
  const etaDisplay = (entry) => {
    if (!entry) return 'Unknown';
    
    // Use the appropriate timestamp based on UTC setting
    const timestampToUse = useUTC ? entry.eta_timestamp_utc : entry.eta_timestamp;
    
    if (timestampToUse) {
      return formatTimestampDirect(timestampToUse);
    }
    
    // Fallback to raw ETA string if no timestamp
    return entry.eta || 'Unknown';
  };

  // Filtering and sorting
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.filter(r => {
      const matchesQuery = !q || [r.name, r.text, vehicleMap(r.vehicle)].some(x => (x||'').toLowerCase().includes(q));
      const vOK = vehicleFilter.length === 0 || vehicleFilter.includes(vehicleMap(r.vehicle));
      const sOK = statusFilter.length === 0 || statusFilter.includes(statusOf(r));
      return matchesQuery && vOK && sOK;
    });
  }, [data, query, vehicleFilter, statusFilter]);
  const [sortBy, setSortBy] = useState({ key: 'timestamp', dir: 'desc' });
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
    const times = data.map(e => e.minutes_until_arrival).filter(x => typeof x === 'number');
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
    const rows = ['Time,Name,Message,Vehicle,ETA,Status'];
    sorted.forEach(r => {
      const ts = formatTimestampDirect(useUTC ? r.timestamp_utc : r.timestamp);
      const etaStr = etaDisplay(r);
      const row = [ts, r.name, (r.text||'').replace(/"/g,'""'), vehicleMap(r.vehicle), etaStr, statusOf(r)];
      rows.push(row.map(v => /[",\n]/.test(String(v)) ? '"'+String(v)+'"' : String(v)).join(','));
    });
    const blob = new Blob([rows.join('\n')], {type: 'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'responders.csv'; a.click(); URL.revokeObjectURL(url);
  };

  const clearAll = async () => {
    try {
      const r = await fetch('/api/clear-all', { method: 'POST' });
      if (r.ok) {
        await fetchData();
      } else {
        alert('Clear all disabled. Set ALLOW_CLEAR_ALL=true or provide X-API-Key.');
      }
    } catch (e) { alert('Failed to clear'); }
  };

  const sortButton = (label, key) => (
    <button
      className="btn"
      aria-sort={sortBy.key===key ? (sortBy.dir==='asc'?'ascending':'descending') : 'none'}
      onClick={() => setSortBy(s => ({ key, dir: s.key===key && s.dir==='desc' ? 'asc' : 'desc' }))}
      title={`Sort by ${label}`}
    >{label} {sortBy.key===key ? (sortBy.dir==='asc'?'▲':'▼') : ''}</button>
  );

  return (
    <div className="App">
      {/* App Bar */}
      <div className="app-bar">
        <div className="left">
          <img src="/scvsar-logo.png" alt="SCVSAR" className="logo" onError={(e)=>e.currentTarget.style.display='none'} />
          <div className="app-title">SCVSAR Response Tracker</div>
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
              <div className="menu-item" onClick={()=>window.location.href='/'}>Profile</div>
              <div className="menu-item" onClick={()=>window.location.href='/'}>Switch Account</div>
              <div className="menu-item" onClick={()=>{ sessionStorage.setItem('respondr_logging_out','true'); window.location.href = user?.logout_url || '/oauth2/sign_out?rd=/'; }}>Logout</div>
            </div>
          )}
        </div>
      </div>

      {/* Secondary Toolbar */}
      <div className="toolbar">
        <input className="search-input" placeholder="Search name/message/vehicle…" value={query} onChange={e=>setQuery(e.target.value)} />
        <div className="chip-row" aria-label="Quick filters">
          {Array.from(new Set(
            data
              .map(e => vehicleMap(e.vehicle))
              // Exclude status-like values from vehicle chips to avoid duplicates
              .filter(v => v && v !== 'Not Responding' && v !== 'Unknown')
          ))
            .sort((a,b)=>String(a).localeCompare(String(b)))
            .map(v => (
              <div key={v} className={"chip "+(vehicleFilter.includes(v)?'active':'')} onClick={()=>toggleInArray(vehicleFilter, v, setVehicleFilter)}>{v}</div>
            ))}
          {["Responding","Not Responding","Unknown"].map(s => (
            <div key={s} className={"chip "+(statusFilter.includes(s)?'active':'')} onClick={()=>toggleInArray(statusFilter, s, setStatusFilter)}>{s}</div>
          ))}
        </div>
        <div className="controls">
          <label className="toggle"><input type="checkbox" checked={live} onChange={e=>setLive(e.target.checked)} /> Live</label>
          <label className="toggle"><input type="checkbox" checked={useUTC} onChange={e=>setUseUTC(e.target.checked)} /> UTC</label>
          <button className="btn" onClick={()=>fetchData()} title="Refresh now">Refresh</button>
          <button className="btn" onClick={exportCsv} title="Export CSV">Export</button>
          <button className="btn" onClick={clearAll} title="Clear all data">Clear</button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-title">Responders</div>
          <div className="stat-value">{totalResponders}</div>
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

      {/* Table */}
      <div className="table-wrap">
        <table className="dashboard-table" role="table">
          <thead>
            <tr>
              <th className="col-time">{sortButton('Time','timestamp')}</th>
              <th>Name</th>
              <th>Message</th>
              <th>Vehicle</th>
              <th>{sortButton('ETA','eta')}</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              [...Array(5)].map((_,i)=> (
                <tr key={i}><td className="col-time"><div className="skeleton" style={{width:'80px'}}/></td><td><div className="skeleton"/></td><td><div className="skeleton"/></td><td><div className="skeleton" style={{width:'60px'}}/></td><td><div className="skeleton" style={{width:'80px'}}/></td><td><div className="skeleton" style={{width:'100px'}}/></td></tr>
              ))
            )}
            {!isLoading && sorted.length === 0 && (
              <tr><td colSpan="6" className="empty">No data. <button className="btn" onClick={()=>{ setQuery(''); setVehicleFilter([]); setStatusFilter([]); }}>Clear filters</button></td></tr>
            )}
            {!isLoading && sorted.map((entry, index) => {
              const s = statusOf(entry);
              const pillClass = s==='Responding' ? 'status-responding' : (s==='Not Responding' ? 'status-not' : 'status-unknown');
              return (
                <tr key={index}>
                  <td className="col-time" title={formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}>{formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}</td>
                  <td>{entry.name}</td>
                  <td>
                    <div className="msg">{entry.text}</div>
                  </td>
                  <td>{vehicleMap(entry.vehicle)}</td>
                  <td title={etaDisplay(entry)}>{etaDisplay(entry)}</td>
                  <td>
                    <span className={`status-pill ${pillClass}`} aria-label={`Status: ${s}`}>{s}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function App() {
  // Check if user is logging out - this will show the logout page after auth redirect
  const [isLoggingOut, setIsLoggingOut] = React.useState(false);
  const shouldUseMobile = React.useCallback(() => {
    try {
      if (typeof window === 'undefined') return false;
      const params = new URLSearchParams(window.location.search);
      const desktopParam = params.get('desktop');
      if (desktopParam === '1' || desktopParam === 'true') {
        try { window.localStorage.setItem('respondr_force_desktop','true'); } catch {}
        return false;
      }
      const forced = (() => { try { return window.localStorage.getItem('respondr_force_desktop') === 'true'; } catch { return false; } })();
      if (forced) return false;
      const mq = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
      return Boolean(mq);
    } catch { return false; }
  }, []);
  
  React.useEffect(() => {
    // Check for logout marker in sessionStorage
    const loggingOut = sessionStorage.getItem('respondr_logging_out') === 'true';
    if (loggingOut) {
      // Clear the marker
      sessionStorage.removeItem('respondr_logging_out');
      setIsLoggingOut(true);
    }
  }, []);
  
  return (
    <Router>
      <Routes>
  <Route path="/" element={isLoggingOut ? <Logout /> : (shouldUseMobile() ? <Navigate to="/m" replace /> : <MainApp />)} />
  <Route path="/m" element={<MobileView />} />
        <Route path="/logout" element={<Logout />} />
      </Routes>
    </Router>
  );
}

export default App;
