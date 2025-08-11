import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './App.css';

// Minimal, focused mobile view: Name, Vehicle, ETA for Responding only
export default function MobileView() {
  const [data, setData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [live, setLive] = useState(true);
  const [authChecked, setAuthChecked] = useState(false);
  const [accessDenied, setAccessDenied] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      // check auth first
      try {
        const ur = await fetch('/api/user');
        if (!ur.ok) throw new Error('auth');
        const uj = await ur.json();
        setAuthChecked(true);
        if (!uj.authenticated || uj.error === 'Access denied') {
          setIsLoading(false);
          setAccessDenied(uj);
          setData([]);
          return;
        }
      } catch {}
      const res = await fetch('/api/responders', { headers: { 'Accept': 'application/json' }});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setIsLoading(false);
      setLastUpdated(new Date());
    } catch (e) {
      console.error(e);
      setError(String(e.message || e));
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    let id;
    const poll = async () => {
      id = setTimeout(async () => {
        try { if (live) await fetchData(); } finally { poll(); }
      }, 15000);
    };
    poll();
    return () => { if (id) clearTimeout(id); };
  }, [fetchData, live]);

  // Helpers local to this view
  const statusOf = (entry) => {
    if (entry.arrival_status) {
      if (entry.arrival_status === 'Not Responding') return 'Not Responding';
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

  const parseTs = (ts) => {
    if (!ts) return null;
    const s = typeof ts === 'string' && ts.includes(' ') && !ts.includes('T') ? ts.replace(' ', 'T') : ts;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
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
        const dt = new Date(base.getTime());
        dt.setHours(hh, mm, 0, 0);
        if (dt.getTime() <= base.getTime()) dt.setDate(dt.getDate() + 1);
        return dt.getTime();
      }
    } catch {}
    return Number.NaN;
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
  const uniqueTotalResponders = useMemo(() => {
    const ids = new Set(data.filter(e => statusOf(e) === 'Responding').map(e => e.user_id || e.name).filter(Boolean));
    return ids.size;
  }, [data]);
  const uniqueFilteredResponders = deduped.length;
  const avgMinutes = useMemo(() => {
    const times = deduped.map(e => e.minutes_until_arrival).filter(x => typeof x === 'number');
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
          <div className="mobile-stat-value">{uniqueFilteredResponders}/{uniqueTotalResponders}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Avg ETA</div>
          <div className="mobile-stat-value">{avgText}</div>
        </div>
      </div>

      {error && (
        <div className="empty" role="alert">{error}</div>
      )}
      {authChecked && accessDenied && (
        <div className="empty" role="alert">
          {accessDenied.message || 'Access denied'}
          <div style={{marginTop:12}}>
            <a className="btn" href={(typeof window!=='undefined' && window.location.host.endsWith(':3100')) ? 'http://localhost:8000/oauth2/sign_out?rd=/' : '/oauth2/sign_out?rd=/'}>Sign out</a>
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
          <input type="checkbox" checked={live} onChange={(e)=>setLive(e.target.checked)} /> Live
        </label>
      </div>
    </div>
  );
}
