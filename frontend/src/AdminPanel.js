import React, { useState, useEffect } from 'react';
import './AdminPanel.css';

function AdminPanel() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('users');
  const [showCreateUser, setShowCreateUser] = useState(false);

  useEffect(() => {
    if (activeTab === 'users') {
      fetchUsers();
    }
  }, [activeTab]);

  const fetchUsers = async () => {
    setLoading(true);
    setError('');
    try {
      import React, { useState, useEffect } from 'react';
import './AdminPanel.css';
import { apiUrl } from './config';

function AdminPanel() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('users');
  const [showCreateUser, setShowCreateUser] = useState(false);

  useEffect(() => {
    if (activeTab === 'users') {
      fetchUsers();
    }
  }, [activeTab]);

  const fetchUsers = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(apiUrl('/api/auth/local/admin/users'), {
        credentials: 'include'
      });
      
      if (response.ok) {
        const data = await response.json();
        setUsers(data.users || []);
      } else {
        setError('Failed to load users');
      }
    } catch (err) {
      setError('Network error loading users');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-panel">
      <div className="admin-header">
        <div className="admin-header-content">
          <div className="admin-title">
            <h1>Admin Panel</h1>
            <p>Manage local user accounts and system settings</p>
          </div>
          <button 
            className="btn btn-secondary back-to-dashboard"
            onClick={() => window.location.href = '/'}
            title="Return to Dashboard"
          >
            ← Back to Dashboard
          </button>
        </div>
      </div>

      <div className="admin-tabs">
        <button 
          className={`tab ${activeTab === 'users' ? 'active' : ''}`}
          onClick={() => setActiveTab('users')}
        >
          User Management
        </button>
        <button 
          className={`tab ${activeTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveTab('settings')}
        >
          Settings
        </button>
      </div>

      <div className="admin-content">
        {activeTab === 'users' && (
          <UserManagement 
            users={users}
            setUsers={setUsers}
            loading={loading}
            error={error}
            showCreateUser={showCreateUser}
            setShowCreateUser={setShowCreateUser}
            onRefresh={fetchUsers}
          />
        )}
        
        {activeTab === 'settings' && (
          <SystemSettings />
        )}
      </div>
    </div>
  );
}

function UserManagement({ users, setUsers, loading, error, showCreateUser, setShowCreateUser, onRefresh }) {
  const [resetPasswordUser, setResetPasswordUser] = useState(null);

  const handleDeleteUser = async (username) => {
    if (!window.confirm(`Are you sure you want to delete user "${username}"?`)) {
      return;
    }

    try {
      const response = await fetch(apiUrl(`/api/auth/local/admin/users/${username}`), {
        method: 'DELETE',
        credentials: 'include'
      });
      
      const data = await response.json();
      
      if (response.ok && data.success) {
        onRefresh(); // Refresh the user list
        alert(`User "${username}" deleted successfully`);
      } else {
        alert(data.detail || data.message || 'Failed to delete user');
      }
    } catch (err) {
      console.error('Error deleting user:', err);
      alert('Failed to delete user: Network error');
    }
  };

  const handleResetPassword = (user) => {
    setResetPasswordUser(user);
  };

  return (
    <div className="user-management">
      <div className="section-header">
        <h2>Local User Accounts</h2>
        <button 
          className="btn btn-primary"
          onClick={() => setShowCreateUser(true)}
        >
          Create New User
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">Loading users...</div>
      ) : (
        <div className="users-table">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Email</th>
                <th>Display Name</th>
                <th>Organization</th>
                <th>Admin</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => (
                <tr key={user.username}>
                  <td className="username">{user.username}</td>
                  <td>{user.email}</td>
                  <td>{user.display_name}</td>
                  <td>{user.organization || '-'}</td>
                  <td>
                    <span className={`badge ${user.is_admin ? 'admin' : 'user'}`}>
                      {user.is_admin ? 'Admin' : 'User'}
                    </span>
                  </td>
                  <td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}</td>
                  <td className="actions">
                    <button 
                      className="btn btn-small btn-secondary"
                      onClick={() => handleResetPassword(user)}
                    >
                      Reset Password
                    </button>
                    <button 
                      className="btn btn-small btn-danger"
                      onClick={() => handleDeleteUser(user.username)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          
          {users.length === 0 && (
            <div className="empty-state">
              <p>No local users found. Create one to get started.</p>
            </div>
          )}
        </div>
      )}

      {showCreateUser && (
        <CreateUserModal 
          onClose={() => setShowCreateUser(false)}
          onSuccess={onRefresh}
        />
      )}

      {resetPasswordUser && (
        <ResetPasswordModal 
          user={resetPasswordUser}
          onClose={() => setResetPasswordUser(null)}
          onSuccess={onRefresh}
        />
      )}
    </div>
  );
}

function CreateUserModal({ onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    confirmPassword: '',
    email: '',
    display_name: '',
    organization: '',
    is_admin: false
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters long');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const response = await fetch(apiUrl('/api/auth/local/admin/create-user'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          username: formData.username,
          password: formData.password,
          email: formData.email,
          display_name: formData.display_name,
          organization: formData.organization,
          is_admin: formData.is_admin
        }),
      });

      const data = await response.json();

      if (data.success) {
        onSuccess();
        onClose();
      } else {
        setError(data.error || 'Failed to create user');
      }
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header">
          <h3>Create New User</h3>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>
        
        <form onSubmit={handleSubmit} className="modal-form">
          {error && <div className="error-message">{error}</div>}
          
          <div className="form-row">
            <div className="form-group">
              <label>Username *</label>
              <input
                type="text"
                name="username"
                value={formData.username}
                onChange={handleInputChange}
                required
                disabled={loading}
              />
            </div>
            
            <div className="form-group">
              <label>Email *</label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleInputChange}
                required
                disabled={loading}
              />
            </div>
          </div>

          <div className="form-group">
            <label>Display Name *</label>
            <input
              type="text"
              name="display_name"
              value={formData.display_name}
              onChange={handleInputChange}
              required
              disabled={loading}
            />
          </div>

          <div className="form-group">
            <label>Organization</label>
            <input
              type="text"
              name="organization"
              value={formData.organization}
              onChange={handleInputChange}
              disabled={loading}
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Password *</label>
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleInputChange}
                required
                minLength={8}
                disabled={loading}
              />
            </div>
            
            <div className="form-group">
              <label>Confirm Password *</label>
              <input
                type="password"
                name="confirmPassword"
                value={formData.confirmPassword}
                onChange={handleInputChange}
                required
                disabled={loading}
              />
            </div>
          </div>

          <div className="form-group checkbox-group">
            <label>
              <input
                type="checkbox"
                name="is_admin"
                checked={formData.is_admin}
                onChange={handleInputChange}
                disabled={loading}
              />
              Grant admin privileges
            </label>
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn btn-primary">
              {loading ? 'Creating...' : 'Create User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ResetPasswordModal({ user, onClose, onSuccess }) {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters long');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const response = await fetch(apiUrl('/api/auth/local/admin/reset-password'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          username: user.username,
          new_password: newPassword
        }),
      });

      const data = await response.json();

      if (data.success) {
        onSuccess();
        onClose();
      } else {
        setError(data.error || 'Failed to reset password');
      }
    } catch (err) {
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal">
        <div className="modal-header">
          <h3>Reset Password for {user.username}</h3>
          <button className="close-btn" onClick={onClose}>&times;</button>
        </div>
        
        <form onSubmit={handleSubmit} className="modal-form">
          {error && <div className="error-message">{error}</div>}
          
          <div className="form-group">
            <label>New Password *</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              disabled={loading}
            />
          </div>
          
          <div className="form-group">
            <label>Confirm New Password *</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              disabled={loading}
            />
          </div>

          <div className="modal-actions">
            <button type="button" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn btn-primary">
              {loading ? 'Resetting...' : 'Reset Password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SystemSettings() {
  return (
    <div className="system-settings">
      <div className="section-header">
        <h2>System Settings</h2>
      </div>
      
      <div className="settings-section">
        <h3>Authentication</h3>
        <div className="setting-item">
          <label>Local Authentication</label>
          <span className="status enabled">Enabled</span>
        </div>
        <div className="setting-item">
          <label>SSO Authentication</label>
          <span className="status enabled">Enabled</span>
        </div>
      </div>

      <div className="settings-section">
        <h3>Email Domains</h3>
        <div className="setting-item">
          <label>Allowed Domains</label>
          <span className="value">scvsar.org, snoco.org, respondr.local</span>
        </div>
      </div>

      <div className="settings-section">
        <h3>Storage</h3>
        <div className="setting-item">
          <label>Primary Storage</label>
          <span className="status enabled">Azure Table Storage</span>
        </div>
        <div className="setting-item">
          <label>Fallback Storage</label>
          <span className="status enabled">In-Memory</span>
        </div>
      </div>
    </div>
  );
}

export default AdminPanel;