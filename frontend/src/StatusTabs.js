import React, { useState, useEffect, useMemo } from 'react';
import './StatusTabs.css';
import { apiCall } from './api';
import { responderKey } from './responderIdentity';
import { validateResponderData } from './responderData';

const unfilteredUrl = (endpoint) => endpoint;

const StatusTabs = ({ 
  data, 
  isLoading, 
  error, 
  selected, 
  editMode, 
  isAdmin, 
  sortBy, 
  setSortBy, 
  toggleRow, 
  toggleAll,
  toggleAllVisible,
  statusOf, 
  unitOf, 
  resolveVehicle, 
  etaDisplay, 
  formatTimestampDirect, 
  useUTC,
  statusFilter = [],
  vehicleFilter = [],
  query = '',
  refreshNonce = 0,
  geocitiesMode = false,
  getTimeFilterUrl = unfilteredUrl,
  onCurrentViewChange,
  // Controlled tab props (optional)
  activeTab: controlledActiveTab,
  onTabChange,
}) => {
  // Support controlled or uncontrolled active tab
  const [internalActiveTab, setInternalActiveTab] = useState('current');
  const activeTab = (typeof controlledActiveTab !== 'undefined' && controlledActiveTab !== null)
    ? controlledActiveTab
    : internalActiveTab;
  const changeTab = (tab) => {
    if (typeof onTabChange === 'function') onTabChange(tab);
    if (typeof controlledActiveTab === 'undefined' || controlledActiveTab === null) {
      setInternalActiveTab(tab);
    }
  };
  const [currentStatusData, setCurrentStatusData] = useState([]);
  const [currentStatusLoading, setCurrentStatusLoading] = useState(true);
  const [currentStatusError, setCurrentStatusError] = useState(null);

  useEffect(() => {
    if (activeTab !== 'current') return;
    let cancelled = false;
    const fetchCurrentStatus = async () => {
      try {
        setCurrentStatusError(null);
        setCurrentStatusLoading(true);
        const url = getTimeFilterUrl('/api/current-status');
        if (!url) throw new Error('Choose a valid start time.');
        const response = await apiCall(`${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const currentStatus = validateResponderData(await response.json());

        if (!cancelled) setCurrentStatusData(currentStatus);
      } catch (err) {
        console.error('Failed to fetch current status:', err);
        if (!cancelled) setCurrentStatusError(err.message);
      } finally {
        if (!cancelled) setCurrentStatusLoading(false);
      }
    };
    fetchCurrentStatus();
    return () => { cancelled = true; };
  }, [data, activeTab, refreshNonce, getTimeFilterUrl]);

  // Apply filters to current status data (status / vehicle / search)
  const filteredCurrentStatus = useMemo(() => {
    if (!currentStatusData?.length) return [];
    const q = query.trim().toLowerCase();
    const filtered = currentStatusData.filter(entry => {
      const status = statusOf(entry);
      if (statusFilter.length && !statusFilter.includes(status)) return false;
      const vehResolved = resolveVehicle(entry);
      if (vehicleFilter.length && !vehicleFilter.includes(vehResolved)) return false;
      if (q) {
        const hay = [entry.name, entry.text, vehResolved, status].map(x => String(x||'').toLowerCase());
        if (!hay.some(h => h.includes(q))) return false;
      }
      
      return true;
    });
    
    return filtered;
  }, [currentStatusData, statusFilter, vehicleFilter, query, statusOf, resolveVehicle]);

  useEffect(() => {
    if (onCurrentViewChange) onCurrentViewChange({
      rows: filteredCurrentStatus, total: currentStatusData.length,
      loading: currentStatusLoading, error: currentStatusError,
    });
  }, [filteredCurrentStatus, currentStatusData, currentStatusLoading, currentStatusError, onCurrentViewChange]);

  // Sort current status data after filtering
  const sortedCurrentStatus = useMemo(() => {
    if (!filteredCurrentStatus?.length) return [];
    
    const sorted = [...filteredCurrentStatus].sort((a, b) => {
      const key = sortBy.key;
      const dir = sortBy.dir === 'desc' ? -1 : 1;
      
      let aVal, bVal;
      
      switch (key) {
        case 'timestamp':
          aVal = new Date(a.timestamp_utc || a.timestamp || 0).getTime();
          bVal = new Date(b.timestamp_utc || b.timestamp || 0).getTime();
          break;
        case 'eta':
          // Sort by eta_timestamp if available, otherwise by eta string
          aVal = (a.eta_timestamp_utc || a.eta_timestamp) ? new Date(a.eta_timestamp_utc || a.eta_timestamp).getTime() : (a.eta === 'Cancelled' ? 0 : 999999999999);
          bVal = (b.eta_timestamp_utc || b.eta_timestamp) ? new Date(b.eta_timestamp_utc || b.eta_timestamp).getTime() : (b.eta === 'Cancelled' ? 0 : 999999999999);
          break;
        default:
          aVal = String(a[key] || '').toLowerCase();
          bVal = String(b[key] || '').toLowerCase();
      }
      
      if (aVal < bVal) return -1 * dir;
      if (aVal > bVal) return 1 * dir;
      return 0;
    });
    
    return sorted;
  }, [filteredCurrentStatus, sortBy]);

  // Sort all messages data (existing logic)
  const sortedAllMessages = useMemo(() => {
    if (!data?.length) return [];
    
    const sorted = [...data].sort((a, b) => {
      const key = sortBy.key;
      const dir = sortBy.dir === 'desc' ? -1 : 1;
      
      let aVal, bVal;
      
      switch (key) {
        case 'timestamp':
          aVal = new Date(a.timestamp_utc || a.timestamp || 0).getTime();
          bVal = new Date(b.timestamp_utc || b.timestamp || 0).getTime();
          break;
        case 'eta':
          aVal = (a.eta_timestamp_utc || a.eta_timestamp) ? new Date(a.eta_timestamp_utc || a.eta_timestamp).getTime() : (a.eta === 'Cancelled' ? 0 : 999999999999);
          bVal = (b.eta_timestamp_utc || b.eta_timestamp) ? new Date(b.eta_timestamp_utc || b.eta_timestamp).getTime() : (b.eta === 'Cancelled' ? 0 : 999999999999);
          break;
        default:
          aVal = String(a[key] || '').toLowerCase();
          bVal = String(b[key] || '').toLowerCase();
      }
      
      if (aVal < bVal) return -1 * dir;
      if (aVal > bVal) return 1 * dir;
      return 0;
    });
    
    return sorted;
  }, [data, sortBy]);

  // Optional dedupe for All Messages: keep latest message per user, then sort by current sort key
  const [allLatestOnly, setAllLatestOnly] = useState(false);
  const dedupedAllMessages = useMemo(() => {
    if (!data?.length) return [];
    // Pick latest per user by timestamp
    const latest = new Map();
    const tsOf = (e) => {
      const t = e.timestamp_utc || e.timestamp || 0;
      const d = new Date(t);
      return isNaN(d.getTime()) ? 0 : d.getTime();
    };
    const uidOf = responderKey;
    for (const m of data) {
      const uid = uidOf(m);
      if (!uid) continue;
      const prev = latest.get(uid);
      if (!prev || tsOf(m) > tsOf(prev)) latest.set(uid, m);
    }
    const arr = Array.from(latest.values());
    // Sort using same logic as sortedAllMessages
    const key = sortBy.key;
    const dir = sortBy.dir === 'desc' ? -1 : 1;
    arr.sort((a,b) => {
      let aVal, bVal;
      switch (key) {
        case 'timestamp':
          aVal = new Date(a.timestamp_utc || a.timestamp || 0).getTime();
          bVal = new Date(b.timestamp_utc || b.timestamp || 0).getTime();
          break;
        case 'eta':
          aVal = (a.eta_timestamp_utc || a.eta_timestamp) ? new Date(a.eta_timestamp_utc || a.eta_timestamp).getTime() : (a.eta === 'Cancelled' ? 0 : 999999999999);
          bVal = (b.eta_timestamp_utc || b.eta_timestamp) ? new Date(b.eta_timestamp_utc || b.eta_timestamp).getTime() : (b.eta === 'Cancelled' ? 0 : 999999999999);
          break;
        default:
          aVal = String(a[key] || '').toLowerCase();
          bVal = String(b[key] || '').toLowerCase();
      }
      if (aVal < bVal) return -1 * dir;
      if (aVal > bVal) return 1 * dir;
      return 0;
    });
    return arr;
  }, [data, sortBy]);

  const sortButton = (label, key) => (
    <button
      className="btn sort-btn"
      onClick={() => setSortBy(s => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
      title={`Sort by ${label}`}
    >
      {label} {sortBy.key === key ? (sortBy.dir === 'asc' ? '▲' : '▼') : ''}
    </button>
  );

  const renderTable = (tableData, loading, error, showAllColumns = false) => {
    const visibleIds = (tableData || []).map(r => r.id).filter(Boolean);
    const allVisibleChecked = visibleIds.length > 0 && visibleIds.every(id => selected.has(id)) && selected.size === visibleIds.length;
    return (
  <div className={geocitiesMode ? "table-wrap geocities-table" : "table-wrap"}>
        <table className={geocitiesMode ? "dashboard-table geocities-retro-table" : "dashboard-table"} role="table">
          <thead>
            <tr>
              {editMode && showAllColumns && (
                <th style={{ width: 36 }}>
                  <input 
                    type="checkbox" 
                    aria-label="Select all" 
                    checked={allVisibleChecked} 
                    onChange={() => toggleAllVisible(visibleIds)} 
                  />
                </th>
              )}
              <th className="col-time">{sortButton('Time', 'timestamp')}</th>
              <th>Name</th>
              <th>Team</th>
              <th>Message</th>
              <th>Vehicle</th>
              <th>{sortButton('ETA', 'eta')}</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              [...Array(5)].map((_, i) => (
                <tr key={i}>
                  {editMode && showAllColumns && <td><div className="skeleton" style={{ width: '20px' }} /></td>}
                  <td className="col-time"><div className="skeleton" style={{ width: '80px' }} /></td>
                  <td><div className="skeleton" /></td>
                  <td><div className="skeleton" style={{ width: '80px' }} /></td>
                  <td><div className="skeleton" /></td>
                  <td><div className="skeleton" style={{ width: '60px' }} /></td>
                  <td><div className="skeleton" style={{ width: '80px' }} /></td>
                  <td><div className="skeleton" style={{ width: '100px' }} /></td>
                </tr>
              ))
            )}
            {!loading && error && (
              <tr>
                <td colSpan={editMode && showAllColumns ? "8" : "7"} className="empty error">
                  Error: {error}
                </td>
              </tr>
            )}
            {!loading && !error && tableData.length === 0 && (
              <tr>
                <td colSpan={editMode && showAllColumns ? "8" : "7"} className="empty">
                  {activeTab === 'current' ? (currentStatusData.length ? 'No responders match the filters' : 'No current status data') : 'No messages found'}
                </td>
              </tr>
            )}
            {!loading && !error && tableData.map((entry, index) => {
              const s = statusOf(entry);
              const pillClass = s === 'Responding' ? 'status-responding' : 
                               (s === 'Available' ? 'status-available' : 
                               (s === 'Informational' ? 'status-informational' : 
                               (s === 'Cancelled' ? 'status-cancelled' : 
                               (s === 'Not Responding' ? 'status-not' : 'status-unknown'))));
              
              return (
                <tr key={entry.id || index} className={selected.has(entry.id) ? 'row-selected' : ''}>
                  {editMode && showAllColumns && (
                    <td>
                      <input 
                        type="checkbox" 
                        aria-label={`Select ${entry.name}`} 
                        checked={selected.has(entry.id)} 
                        onChange={() => toggleRow(entry.id)} 
                      />
                    </td>
                  )}
                  <td className="col-time" title={formatTimestampDirect(entry.timestamp_utc || entry.timestamp, useUTC)}>
                    {formatTimestampDirect(entry.timestamp_utc || entry.timestamp, useUTC)}
                  </td>
                  <td>{entry.name}</td>
                  <td>{unitOf(entry)}</td>
                  <td>
                    <div className="msg">{entry.text}</div>
                  </td>
                  <td>{resolveVehicle(entry)}</td>
                  <td title={etaDisplay(entry, useUTC)}>{etaDisplay(entry, useUTC)}</td>
                  <td>
                    <span className={`status-pill ${pillClass}`} aria-label={`Status: ${s}`}>
                      {s}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  // Count by status for current status tab
  const statusCounts = useMemo(() => {
    if (!filteredCurrentStatus?.length) return {};
    
    const counts = {};
    filteredCurrentStatus.forEach(entry => {
      const status = statusOf(entry);
      counts[status] = (counts[status] || 0) + 1;
    });
    
    return counts;
  }, [filteredCurrentStatus, statusOf]);

  return (
    <div className="status-tabs">
      {/* Tab Navigation */}
  <div className="tab-nav">
        <button 
          className={`tab-btn ${activeTab === 'current' ? 'active' : ''}`}
          onClick={() => changeTab('current')}
        >
          <span className="tab-icon">👥</span>
          Current Status
          {currentStatusData?.length > 0 && (
            <span className="tab-badge">{filteredCurrentStatus.length}</span>
          )}
        </button>
        <button 
          className={`tab-btn ${activeTab === 'all' ? 'active' : ''}`}
          onClick={() => changeTab('all')}
        >
          <span className="tab-icon">💬</span>
          All Messages
          {data?.length > 0 && (
            <span className="tab-badge">{data.length}</span>
          )}
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'current' && (
          <div className="current-status-tab">
            {/* Status Summary Cards */}
            {!currentStatusLoading && !currentStatusError && Object.keys(statusCounts).length > 0 && (
              <div className="status-summary">
                {Object.entries(statusCounts).map(([status, count]) => {
                  const cardClass = status === 'Responding' ? 'summary-responding' : 
                                   (status === 'Available' ? 'summary-available' : 
                                   (status === 'Cancelled' ? 'summary-cancelled' : 
                                   (status === 'Not Responding' ? 'summary-not' : 'summary-other')));
                  
                  return (
                    <div key={status} className={`summary-card ${cardClass}`}>
                      <div className="summary-count">{count}</div>
                      <div className="summary-label">{status}</div>
                    </div>
                  );
                })}
              </div>
            )}
            
            {/* Current Status Table */}
            {renderTable(sortedCurrentStatus, currentStatusLoading, currentStatusError, false)}
            
            {!currentStatusLoading && !currentStatusError && currentStatusData?.length > 0 && (
              <div className="tab-footer">
                <small className="tab-help">
                  💡 Showing latest status per person • Updates automatically when new messages arrive
                </small>
              </div>
            )}
          </div>
        )}
        
        {activeTab === 'all' && (
          <div className="all-messages-tab">
            {/* Messages Summary Card */}
            {!isLoading && !error && data?.length > 0 && (
              <div className="status-summary">
                <div className="summary-card summary-other">
                  <div className="summary-count">{data.length}</div>
                  <div className="summary-label">Total Messages</div>
                </div>
                <div className="summary-card summary-other" style={{minWidth:180}}>
                  <div className="summary-label" style={{marginBottom:6}}>View</div>
                  <label className="toggle">
                    <input type="checkbox" checked={allLatestOnly} onChange={e=>setAllLatestOnly(e.target.checked)} /> Latest only
                  </label>
                </div>
              </div>
            )}
            
            {renderTable(
              allLatestOnly ? dedupedAllMessages : sortedAllMessages,
              isLoading,
              error,
              !!(isAdmin && editMode) // show selection column only for All Messages in edit mode
            )}
            
            {!isLoading && !error && data?.length > 0 && (
        <div className="tab-footer">
                <small className="tab-help">
          {allLatestOnly ? '👤 Showing latest message per person • Toggle off to see all messages' : '💬 Showing all messages chronologically • Use filters to narrow down results'}
          {isAdmin && editMode ? ' • Edit mode: select rows to Edit/Delete' : ''}
                </small>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default StatusTabs;
