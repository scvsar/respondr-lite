import React, { useEffect, useState, useCallback } from "react";
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import "./App.css";
import UserInfo from "./UserInfo";
import Logout from './Logout';

function MainApp() {
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const res = await fetch("/api/responders");
      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }
      const json = await res.json();
      setData(json);
      setIsLoading(false);
    } catch (err) {
      console.error("Failed to fetch responder data:", err);
      setError(err.message);
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    
    let pollInterval = 5000; // Start with 5 seconds
    const maxInterval = 60000; // Max 60 seconds
    let currentTimeoutId = null;
    let isCancelled = false;
    
    const pollData = () => {
      if (isCancelled) return;
      
      currentTimeoutId = setTimeout(async () => {
        if (isCancelled) return;
        
        try {
          await fetchData();
          pollInterval = 5000; // Reset to normal interval on success
        } catch (err) {
          // Exponential backoff on error
          pollInterval = Math.min(pollInterval * 2, maxInterval);
        }
        
        if (!isCancelled) {
          pollData(); // Schedule next poll
        }
      }, pollInterval);
    };
    
    pollData();
    
    return () => {
      isCancelled = true;
      if (currentTimeoutId) {
        clearTimeout(currentTimeoutId);
      }
    };
  }, [fetchData]);

  const totalResponders = data.length;

  const avgMinutes = () => {
    const times = data
      .map((entry) => entry.minutes_until_arrival)
      .filter((x) => typeof x === "number");

    if (times.length === 0) return "N/A";
    const avg = times.reduce((a, b) => a + b, 0) / times.length;
    return `${Math.round(avg)} minutes`;
  };

  return (
    <div className="App">
      <header className="App-header">
        <img
          src="/scvsar-logo.png"
          alt="SCVSAR Logo"
          className="logo"
          onError={(e) => {
            e.target.style.display = 'none';
          }}
        />
        <h1>SCVSAR Response Tracker</h1>
        <UserInfo />
        {error && (
          <div className="error-message" style={{
            backgroundColor: '#ffcccc',
            color: '#d00',
            padding: '10px',
            margin: '10px',
            borderRadius: '5px',
            border: '1px solid #d00'
          }}>
            ⚠️ Error loading data: {error}
          </div>
        )}
        {isLoading && !error && (
          <div className="loading-message" style={{color: '#666'}}>
            Loading responder data...
          </div>
        )}
        {!isLoading && !error && (
          <div className="metrics">
            <span>Total Responders: {totalResponders}</span>
            <span>Average ETA: {avgMinutes()}</span>
          </div>
        )}
      </header>
      <table className="dashboard-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Name</th>
            <th>Message</th>
            <th>Vehicle</th>
            <th>ETA</th>
          </tr>
        </thead>
        <tbody>
          {data.slice().reverse().map((entry, index) => (
            <tr key={index}>
              <td>{entry.timestamp}</td>
              <td>{entry.name}</td>
              <td>{entry.text}</td>
              <td>{entry.vehicle}</td>
              <td>{entry.eta_timestamp || entry.eta || "Unknown"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function App() {
  // Check if user is logging out - this will show the logout page after auth redirect
  const [isLoggingOut, setIsLoggingOut] = React.useState(false);
  
  React.useEffect(() => {
    // Check for logout marker in sessionStorage
    const loggingOut = sessionStorage.getItem('respondr_logging_out') === 'true';
    if (loggingOut) {
      // Clear the marker
      sessionStorage.removeItem('respondr_logging_out');
      setIsLoggingOut(true);
    }
  }, []);
  
  return (
    <Router>
      <Routes>
        <Route path="/" element={isLoggingOut ? <Logout /> : <MainApp />} />
        <Route path="/logout" element={<Logout />} />
      </Routes>
    </Router>
  );
}

export default App;
