import React, { useEffect, useState } from 'react';
import './UserInfo.css';

function UserInfo() {
  const [user, setUser] = useState(null);
  const [error, setError] = useState(null);
  const [logoutUrl, setLogoutUrl] = useState('/.auth/logout?post_logout_redirect_uri=/');

  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        // Check if user just logged out
        const justLoggedOut = sessionStorage.getItem('loggedOut');
        const logoutTime = sessionStorage.getItem('logoutTime');
        
        if (justLoggedOut) {
          // If logout was recent (within last 3 seconds), don't fetch user info
          if (logoutTime && (Date.now() - parseInt(logoutTime)) < 3000) {
            setError(null);
            setUser(null);
            return;
          } else {
            // Clean up old logout flags
            sessionStorage.removeItem('loggedOut');
            sessionStorage.removeItem('logoutTime');
          }
        }

        const response = await fetch('/api/user');
        if (response.ok) {
          const userData = await response.json();
          setUser(userData);
          if (userData.logout_url) {
            setLogoutUrl(userData.logout_url);
          }
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
    // Clear any local state before logout
    setUser(null);
    setError(null);
    
    // Add a logout flag to sessionStorage to handle post-logout state
    sessionStorage.setItem('loggedOut', 'true');
    
    // Clear any cached user data
    sessionStorage.removeItem('userData');
    
    // Add a timestamp to prevent immediate re-authentication
    sessionStorage.setItem('logoutTime', Date.now().toString());
    
    // Redirect to logout URL with a clean redirect
    window.location.href = logoutUrl;
  };

  const handleLogin = () => {
    // Redirect to EasyAuth login endpoint
    window.location.href = '/.auth/login/aad?post_login_redirect_uri=' + encodeURIComponent(window.location.pathname);
  };

  if (error) {
    return (
      <div className="user-info error">
        <span>⚠️ {error}</span>
        <button
          className="logout-button"
          onClick={handleLogin}
          title="Sign in"
        >
          🔐 Sign In
        </button>
      </div>
    );
  }

  if (!user) {
    // Check if user just logged out
    const justLoggedOut = sessionStorage.getItem('loggedOut');
    if (justLoggedOut) {
      return (
        <div className="user-info">
          <span>✅ Logged out successfully</span>
          <button
            className="logout-button"
            onClick={handleLogin}
            title="Sign in again"
          >
            🔐 Sign In
          </button>
        </div>
      );
    }
    
    return (
      <div className="user-info loading">
        <span>Loading user info...</span>
      </div>
    );
  }

  if (!user.authenticated || (!user.name && !user.email)) {
    return (
      <div className="user-info error">
        <span>⚠️ Not authenticated</span>
        <button
          className="logout-button"
          onClick={handleLogin}
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
