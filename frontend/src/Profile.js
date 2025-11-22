import React from 'react';
import './App.css';
import { msalInstance } from './auth/msalClient';

export default function Profile({ user }) {
  const onLogout = async () => {
    sessionStorage.setItem('respondr_logging_out','true');
    if (user?.auth_type === 'local') {
        window.localStorage.removeItem("local_jwt");
        sessionStorage.clear();
        window.location.reload();
    } else {
        await msalInstance.logoutRedirect();
    }
  };

  const onSwitch = async () => {
    await onLogout();
  };

  if (!user || !user.authenticated) {
    return (
      <div className="empty">
        Not signed in.
        <div style={{marginTop:12}}>
          <a className="btn" href="/">Sign In</a>
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
        {user.auth_type && <div className="stat-sub">Auth Type: {user.auth_type}</div>}
      </div>
      <div style={{marginTop:16, display:'flex', gap:8}}>
        <button className="btn" onClick={onSwitch}>Switch Account</button>
        <button className="btn" onClick={onLogout}>Logout</button>
        <a className="btn" href="/">Back</a>
      </div>
    </div>
  );
}
