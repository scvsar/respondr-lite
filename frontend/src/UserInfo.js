import React, { useEffect, useState } from 'react';
import './UserInfo.css';

function UserInfo() {
  const [user, setUser] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const response = await fetch('/api/user');
        if (response.ok) {
          const userData = await response.json();
          setUser(userData);
        } else {
          setError('Failed to fetch user information');
        }
      } catch (err) {
        setError('Error loading user information');
        console.error('User info fetch error:', err);
      }
    };

    fetchUserInfo();
  }, []);

  const handleLogout = () => {
    // First set a logout marker in session storage
    sessionStorage.setItem('respondr_logging_out', 'true');
    
    // Then redirect to OAuth2 Proxy logout endpoint
    const logoutUrl = `/oauth2/sign_out`;
    window.location.href = logoutUrl;
  };

  if (error) {
    return (
      <div className="user-info error">
        <span>⚠️ {error}</span>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="user-info loading">
        <span>Loading user info...</span>
      </div>
    );
  }

  // Handle case where user is not properly authenticated
  if (!user.authenticated || (!user.name && !user.email)) {
    return (
      <div className="user-info error">
        <span>⚠️ Not authenticated</span>
        <button 
          className="logout-button" 
          onClick={handleLogout}
          title="Sign in"
        >
          🔐 Sign In
        </button>
      </div>
    );
  }

  return (
    <div className="user-info">
      <div className="user-details">
        <span className="user-name">👤 {user.name || user.email || 'Anonymous'}</span>
        {user.email && user.email !== user.name && (
          <span className="user-email">({user.email})</span>
        )}
      </div>
      <button 
        className="logout-button" 
        onClick={handleLogout}
        title="Sign out"
      >
        🚪 Logout
      </button>
    </div>
  );
}

export default UserInfo;
