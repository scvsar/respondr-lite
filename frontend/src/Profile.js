import React, { useEffect, useState } from 'react';
import './App.css';

export default function Profile() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch('/api/user');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (!cancelled) setUser(j);
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const onLogout = () => {
    sessionStorage.setItem('respondr_logging_out','true');
    window.location.href = (user && user.logout_url) || '/oauth2/sign_out?rd=/';
  };

  const onSwitch = () => {
    // For OAuth2 Proxy, switching accounts is effectively logging out and back in
    sessionStorage.setItem('respondr_logging_out','true');
    window.location.href = '/oauth2/sign_out?rd=/oauth2/start?rd=/';
  };

  if (loading) return <div className="empty">Loading…</div>;
  if (error) return (
    <div className="empty" role="alert">
      {error}
      <div style={{marginTop:12}}>
  <a className="btn" href={(typeof window!=='undefined' && window.location.host.endsWith(':3100')) ? 'http://localhost:8000/oauth2/start?rd=/profile' : '/oauth2/start?rd=/profile'}>Sign In</a>
      </div>
    </div>
  );

  if (!user || !user.authenticated) {
    return (
      <div className="empty">
        Not signed in.
        <div style={{marginTop:12}}>
          <a className="btn" href={(typeof window!=='undefined' && window.location.host.endsWith(':3100')) ? 'http://localhost:8000/oauth2/start?rd=/profile' : '/oauth2/start?rd=/profile'}>Sign In</a>
        </div>
      </div>
    );
  }

  return (
    <div className="App" style={{padding:16}}>
      <h2>Profile</h2>
      <div className="stat-card" style={{maxWidth:600}}>
        <div className="stat-title">Signed in as</div>
        <div className="stat-value" style={{fontSize:18}}>{user.name || user.email}</div>
        {user.email && <div className="stat-sub">{user.email}</div>}
        {user.groups && user.groups.length > 0 && (
          <div className="stat-sub">Groups: {user.groups.join(', ')}</div>
        )}
      </div>
      <div style={{marginTop:16, display:'flex', gap:8}}>
        <button className="btn" onClick={onSwitch}>Switch Account</button>
        <button className="btn" onClick={onLogout}>Logout</button>
        <a className="btn" href="/">Back</a>
      </div>
    </div>
  );
}
