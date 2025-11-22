import React, { useState } from 'react';
import './LoginChoice.css';
import { msalInstance, msalConfig, initializeMsal } from './auth/msalClient';
import { localLogin } from './auth/localAuth';

function LoginChoice() {
  const [showLocalLogin, setShowLocalLogin] = useState(false);

  const handleSSOLogin = async () => {
    if (!msalConfig.isConfigured) {
        alert("Azure AD Login is not configured in this environment.\nPlease use External Login or configure REACT_APP_AAD_CLIENT_ID.");
        return;
    }

    try {
        await initializeMsal();
        await msalInstance.loginRedirect({
            scopes: msalConfig.scopes
        });
    } catch (err) {
        console.error("Login failed", err);
        alert("Login failed: " + err.message);
    }
  };

  const handleLocalLogin = () => {
    setShowLocalLogin(true);
  };

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
        </div>
      </div>
    </div>
  );
}

function LocalLoginForm({ onBack }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await localLogin(email, password);
      // Redirect or reload to trigger AuthGate
      window.location.reload();
    } catch (err) {
      setError(err.message || 'Login failed');
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
            <label htmlFor="email">Email or Username:</label>
            <input
              type="text"
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
      </div>
    </div>
  );
}

export default LoginChoice;