import React, { useState, useEffect, useMemo } from 'react';
import './StatusTabs.css';

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
  statusOf, 
  unitOf, 
  resolveVehicle, 
  etaDisplay, 
  formatTimestampDirect, 
  useUTC,
  statusFilter = [],
  vehicleFilter = [],
  query = '' 
}) => {
  const [activeTab, setActiveTab] = useState('current');
  const [currentStatusData, setCurrentStatusData] = useState([]);
  const [currentStatusLoading, setCurrentStatusLoading] = useState(true);
  const [currentStatusError, setCurrentStatusError] = useState(null);

  // Fetch current status data
  const fetchCurrentStatus = async () => {
    try {
      setCurrentStatusError(null);
      setCurrentStatusLoading(true);
      const response = await fetch('/api/current-status');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const json = await response.json();
      setCurrentStatusData(json);
    } catch (err) {
      console.error('Failed to fetch current status:', err);
      setCurrentStatusError(err.message);
    } finally {
      setCurrentStatusLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'current') {
      fetchCurrentStatus();
    }
  }, [activeTab]);

  // Re-fetch current status when main data updates
  useEffect(() => {
    if (activeTab === 'current' && data.length > 0) {
      fetchCurrentStatus();
    }
  }, [data, activeTab]);

  // Apply filters to current status data (status / vehicle / search)
  const filteredCurrentStatus = useMemo(() => {
    if (!currentStatusData?.length) return [];
    const q = query.trim().toLowerCase();
    return currentStatusData.filter(entry => {
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
  }, [currentStatusData, statusFilter, vehicleFilter, query, statusOf, resolveVehicle]);

  // Sort current status data after filtering
  const sortedCurrentStatus = useMemo(() => {
    if (!filteredCurrentStatus?.length) return [];
    
    const sorted = [...filteredCurrentStatus].sort((a, b) => {
      const key = sortBy.key;
      const dir = sortBy.dir === 'desc' ? -1 : 1;
      
      let aVal, bVal;
      
      switch (key) {
        case 'timestamp':
          aVal = new Date(a.timestamp || 0).getTime();
          bVal = new Date(b.timestamp || 0).getTime();
          break;
        case 'eta':
          // Sort by eta_timestamp if available, otherwise by eta string
          aVal = a.eta_timestamp ? new Date(a.eta_timestamp).getTime() : (a.eta === 'Cancelled' ? 0 : 999999999999);
          bVal = b.eta_timestamp ? new Date(b.eta_timestamp).getTime() : (b.eta === 'Cancelled' ? 0 : 999999999999);
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
          aVal = new Date(a.timestamp || 0).getTime();
          bVal = new Date(b.timestamp || 0).getTime();
          break;
        case 'eta':
          aVal = a.eta_timestamp ? new Date(a.eta_timestamp).getTime() : (a.eta === 'Cancelled' ? 0 : 999999999999);
          bVal = b.eta_timestamp ? new Date(b.eta_timestamp).getTime() : (b.eta === 'Cancelled' ? 0 : 999999999999);
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

  const sortButton = (label, key) => (
    <button
      className="btn sort-btn"
      aria-sort={sortBy.key === key ? (sortBy.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      onClick={() => setSortBy(s => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
      title={`Sort by ${label}`}
    >
      {label} {sortBy.key === key ? (sortBy.dir === 'asc' ? '▲' : '▼') : ''}
    </button>
  );

  const renderTable = (tableData, loading, error, showAllColumns = false) => {
    return (
      <div className="table-wrap">
        <table className="dashboard-table" role="table">
          <thead>
            <tr>
              {editMode && showAllColumns && (
                <th style={{ width: 36 }}>
                  <input 
                    type="checkbox" 
                    aria-label="Select all" 
                    checked={selected.size === tableData.length && tableData.length > 0} 
                    onChange={toggleAll} 
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
                  {activeTab === 'current' ? 'No current status data' : 'No messages found'}
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
                  <td className="col-time" title={formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}>
                    {formatTimestampDirect(useUTC ? entry.timestamp_utc : entry.timestamp)}
                  </td>
                  <td>{entry.name}</td>
                  <td>{unitOf(entry)}</td>
                  <td>
                    <div className="msg">{entry.text}</div>
                  </td>
                  <td>{resolveVehicle(entry)}</td>
                  <td title={etaDisplay(entry)}>{etaDisplay(entry)}</td>
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
          onClick={() => setActiveTab('current')}
        >
          <span className="tab-icon">👥</span>
          Current Status
          {currentStatusData?.length > 0 && (
            <span className="tab-badge">{currentStatusData.length}</span>
          )}
        </button>
        <button 
          className={`tab-btn ${activeTab === 'all' ? 'active' : ''}`}
          onClick={() => setActiveTab('all')}
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
              </div>
            )}
            
            {renderTable(sortedAllMessages, isLoading, error, false)}
            
            {!isLoading && !error && data?.length > 0 && (
              <div className="tab-footer">
                <small className="tab-help">
                  💬 Showing all messages chronologically • Use filters to narrow down results
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
