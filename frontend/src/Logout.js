import React from 'react';
import './Logout.css';

function Logout() {
  return (
    <div className="logout-container">
      <div className="logout-box">
        <h1>You have been logged out</h1>
        <p>You can close this page or sign back in.</p>
        <a href="/" className="signin-button">Sign In</a>
      </div>
    </div>
  );
}

export default Logout;
