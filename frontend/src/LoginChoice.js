import React, { useState, useEffect } from 'react';
import './LoginChoice.css';
import { apiUrl } from './config';

function LoginChoice() {
  const [localAuthEnabled, setLocalAuthEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showLocalLogin, setShowLocalLogin] = useState(false);

  useEffect(() => {
    // Check if local authentication is enabled
    // Optimization: Try to avoid waking ACA on initial page load
    // Strategy:
    // 1. Check if we have a cached value in sessionStorage (from previous check)
    // 2. If not cached, check the API (will wake ACA, but only once per session)
    
    const checkLocalAuth = async () => {
      // First check session cache
      const cached = sessionStorage.getItem('local_auth_enabled');
      if (cached !== null) {
        setLocalAuthEnabled(cached === 'true');
        setLoading(false);
        return;
      }

      // No cache - need to check API (this will wake ACA once per browser session)
      try {
        const response = await fetch(apiUrl('/api/auth/local/enabled'));
        if (response.ok) {
          const data = await response.json();
          const enabled = data.enabled === true;
          setLocalAuthEnabled(enabled);
          // Cache the result for this session
          sessionStorage.setItem('local_auth_enabled', enabled.toString());
        } else {
          setLocalAuthEnabled(false);
          sessionStorage.setItem('local_auth_enabled', 'false');
        }
      } catch (error) {
        console.error('Failed to check local auth status:', error);
        setLocalAuthEnabled(false);
        sessionStorage.setItem('local_auth_enabled', 'false');
      } finally {
        setLoading(false);
      }
    };

    checkLocalAuth();
  }, []);

  const handleSSOLogin = () => {
    // Redirect to EasyAuth login
    window.location.href = '/.auth/login/aad?post_login_redirect_uri=' + encodeURIComponent(window.location.pathname);
  };

  const handleLocalLogin = () => {
    setShowLocalLogin(true);
  };

  if (loading) {
    return (
      <div className="login-choice-container">
        <div className="login-choice-card">
          <div className="loading">Loading...</div>
        </div>
      </div>
    );
  }

  if (showLocalLogin) {
    return <LocalLoginForm onBack={() => setShowLocalLogin(false)} />;
  }

  return (
    <div className="login-choice-container">
      <div className="login-choice-card">
        <div className="login-header">
          <img src="/scvsar-logo.png" alt="SCVSAR Logo" className="login-logo" />
          <h2>SCVSAR Response Tracker</h2>
          <p>Choose your login method</p>
        </div>

        <div className="login-options">
          <button 
            className="login-option sso-login" 
            onClick={handleSSOLogin}
          >
            <div className="login-icon">🏢</div>
            <div className="login-text">
              <h3>SCVSAR Member Login</h3>
              <p>Use your SCVSAR.org account</p>
            </div>
          </button>

          {localAuthEnabled && (
            <button 
              className="login-option local-login" 
              onClick={handleLocalLogin}
            >
              <div className="login-icon">👤</div>
              <div className="login-text">
                <h3>External Login</h3>
                <p>Username and password</p>
              </div>
            </button>
          )}
        </div>

        {!localAuthEnabled && (
          <div className="login-note">
            <p>External user login is currently disabled. Please contact an administrator.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function LocalLoginForm({ onBack }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await fetch(apiUrl('/api/auth/local/login'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (data.success) {
        // Set session hint to allow AuthGate to wake ACA on next visit
        localStorage.setItem('respondr_session_hint', 'true');
        // Redirect to main app
        window.location.href = '/';
      } else {
        setError(data.error || 'Login failed');
      }
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-choice-container">
      <div className="login-choice-card">
        <div className="login-header">
          <button className="back-button" onClick={onBack}>← Back</button>
          <img src="/scvsar-logo.png" alt="SCVSAR Logo" className="login-logo" />
          <h2>External Login</h2>
          <p>Enter your credentials</p>
        </div>

        <form onSubmit={handleSubmit} className="local-login-form">
          {error && <div className="error-message">{error}</div>}
          
          <div className="form-group">
            <label htmlFor="username">Username:</label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={loading}
              autoComplete="username"
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password:</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
              autoComplete="current-password"
            />
          </div>

          <button 
            type="submit" 
            className="submit-button"
            disabled={loading}
          >
            {loading ? 'Signing In...' : 'Sign In'}
          </button>
        </form>

        <div className="login-help">
          <p>Don't have an account? Contact your SCVSAR coordinator.</p>
        </div>
      </div>
    </div>
  );
}

export default LoginChoice;