import React, { useEffect, useState, useCallback, useMemo } from "react";
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import "./App.css";
import Logout from './Logout';
import MobileView from './MobileView';
import Profile from './Profile';

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
    return `/oauth2/start?rd=${rd}`;
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
          // Not authenticated: redirect to sign-in preserving target
          window.location.href = signInUrl(loc.pathname || '/');
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
    return (
      <div className="empty" role="alert">
        {denied.message || 'Access denied'}
        <div style={{marginTop:12}}>
          <a className="btn" href="/oauth2/sign_out?rd=/">Sign out</a>
        </div>
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
  const [statusFilter, setStatusFilter] = useState(["Responding"]); // ["Responding","Not Responding","Unknown"]
  const [live, setLive] = useState(true);
  const [useUTC, setUseUTC] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [user, setUser] = useState(null);
  // popover removed
  const [editMode, setEditMode] = useState(false);
  const [selected, setSelected] = useState(()=>new Set());
  const [showEditor, setShowEditor] = useState(false);
  const [editingId, setEditingId] = useState(null);
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
    const rows = ['Time,Name,Team,Message,Vehicle,ETA,Status'];
    sorted.forEach(r => {
      const ts = formatTimestampDirect(useUTC ? r.timestamp_utc : r.timestamp);
      const etaStr = etaDisplay(r);
      const row = [ts, r.name, unitOf(r), (r.text||'').replace(/"/g,'""'), vehicleMap(r.vehicle), etaStr, statusOf(r)];
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
    setEditingId(null);
    resetForm({ timestamp: new Date().toISOString() });
    setShowEditor(true);
  };
  const openEdit = () => {
    if (selected.size !== 1) return;
    const id = Array.from(selected)[0];
    const item = data.find(x => String(x.id) === String(id));
    if (!item) return;
    setEditingId(id);
    resetForm(item);
    setShowEditor(true);
  };
  const saveForm = async () => {
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
    await fetchData();
  };
  const deleteSelected = async () => {
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
              <div className="menu-item" onClick={()=>window.location.href='/profile'}>Profile</div>
              <div className="menu-item" onClick={()=>{ 
                try { window.localStorage.removeItem('respondr_force_desktop'); } catch {}
                const u = new URL(window.location.origin + '/m');
                u.searchParams.set('mobile','1');
                window.location.href = u.toString();
              }}>Mobile Site</div>
              <div className="menu-item" onClick={()=>{ 
                sessionStorage.setItem('respondr_logging_out','true'); 
                const host = window.location.host;
                const url = host.endsWith(':3100') ? 'http://localhost:8000/oauth2/sign_out?rd=/oauth2/start?rd=/' : '/oauth2/sign_out?rd=/oauth2/start?rd=/';
                window.location.href = url; 
              }}>Switch Account</div>
              <div className="menu-item" onClick={()=>{ 
                sessionStorage.setItem('respondr_logging_out','true'); 
                const host = window.location.host;
                const url = host.endsWith(':3100') ? 'http://localhost:8000/oauth2/sign_out?rd=/' : (user?.logout_url || '/oauth2/sign_out?rd=/');
                window.location.href = url; 
              }}>Logout</div>
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
          {/* Clear-all removed; use Edit Mode delete instead */}
          <span style={{width:12}} />
          <label className="toggle"><input type="checkbox" checked={editMode} onChange={e=>{ setEditMode(e.target.checked); setSelected(new Set()); }} /> Edit</label>
          {editMode && (
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
              {editMode && (
                <th style={{width:36}}>
                  <input type="checkbox" aria-label="Select all" checked={selected.size===sorted.length && sorted.length>0} onChange={toggleAll} />
                </th>
              )}
              <th className="col-time">{sortButton('Time','timestamp')}</th>
              <th>Name</th>
              <th>Team</th>
              <th>Message</th>
              <th>Vehicle</th>
              <th>{sortButton('ETA','eta')}</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              [...Array(5)].map((_,i)=> (
                <tr key={i}><td className="col-time"><div className="skeleton" style={{width:'80px'}}/></td><td><div className="skeleton"/></td><td><div className="skeleton" style={{width:'80px'}}/></td><td><div className="skeleton"/></td><td><div className="skeleton" style={{width:'60px'}}/></td><td><div className="skeleton" style={{width:'80px'}}/></td><td><div className="skeleton" style={{width:'100px'}}/></td></tr>
              ))
            )}
            {!isLoading && sorted.length === 0 && (
              <tr><td colSpan="7" className="empty">No data. <button className="btn" onClick={()=>{ setQuery(''); setVehicleFilter([]); setStatusFilter([]); }}>Clear filters</button></td></tr>
            )}
            {!isLoading && sorted.map((entry, index) => {
              const s = statusOf(entry);
              const pillClass = s==='Responding' ? 'status-responding' : (s==='Not Responding' ? 'status-not' : 'status-unknown');
              return (
                <tr key={entry.id || index} className={selected.has(entry.id)?'row-selected':''}>
                  {editMode && (
                    <td>
                      <input type="checkbox" aria-label={`Select ${entry.name}`} checked={selected.has(entry.id)} onChange={()=>toggleRow(entry.id)} />
                    </td>
                  )}
                  <td className="col-time" title={formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}>{formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}</td>
                  <td>{entry.name}</td>
                  <td>{unitOf(entry)}</td>
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
      </Routes>
    </Router>
  );
}

export default App;
