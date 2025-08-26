import React from 'react';
import './Logout.css';

function Logout() {
  return (
    <div className="logout-container">
      <div className="logout-box">
        <h1>You have been logged out</h1>
        <p>You can close this page or sign back in.</p>
  <a href={(typeof window!=='undefined' && window.location.host.endsWith(':3100')) ? 'http://localhost:8000/oauth2/start?rd=/' : '/.auth/login/aad?post_login_redirect_uri=/'} className="signin-button">Sign In</a>
      </div>
    </div>
  );
}

export default Logout;
