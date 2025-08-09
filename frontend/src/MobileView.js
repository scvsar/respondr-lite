import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './App.css';

// Minimal, focused mobile view: Name, Vehicle, ETA for Responding only
export default function MobileView() {
  const [data, setData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [live, setLive] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
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

  // Sort by most recent message (timestamp) descending
  const sorted = useMemo(() => {
    const arr = [...responding];
    arr.sort((a,b) => {
      const at = parseTs(a.timestamp)?.getTime() || 0;
      const bt = parseTs(b.timestamp)?.getTime() || 0;
      return bt - at; // newest first
    });
    return arr;
  }, [responding]);

  // Summary stats (over responding only)
  const totalResponding = responding.length;
  const avgMinutes = useMemo(() => {
    const times = responding.map(e => e.minutes_until_arrival).filter(x => typeof x === 'number');
    if (!times.length) return null;
    const avg = Math.round(times.reduce((a,b)=>a+b,0) / times.length);
    return avg; // minutes
  }, [responding]);

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
          <div className="mobile-stat-label">Responding</div>
          <div className="mobile-stat-value">{totalResponding}</div>
        </div>
        <div className="mobile-stat">
          <div className="mobile-stat-label">Avg ETA</div>
          <div className="mobile-stat-value">{avgText}</div>
        </div>
      </div>

      {error && (
        <div className="empty" role="alert">{error}</div>
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
              <div className="mobile-vehicle">{vehicleMap(e.vehicle)}</div>
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
