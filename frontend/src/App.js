import React, { useEffect, useState, useCallback } from "react";
import "./App.css";

function App() {
  const [data, setData] = useState([]);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/responders");
      const json = await res.json();
      setData(json);
    } catch (err) {
      console.error("Failed to fetch responder data:", err);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const totalResponders = data.length;

  const avgMinutes = () => {
    const times = data
      .map((entry) => {
        const match = entry.eta.match(/(\d+)\s*min/);
        if (match) return parseInt(match[1], 10);
        return null;
      })
      .filter((x) => x !== null);

    if (times.length === 0) return "N/A";
    const avg = times.reduce((a, b) => a + b, 0) / times.length;
    return `${Math.round(avg)} minutes`;
  };

  return (
    <div className="App">
      <header className="App-header">
        <img
          src="https://scvsar.org/wp-content/uploads/2016/10/snohomish_county_volunteer_search_and_rescue.png"
          alt="SCVSAR Logo"
          className="logo"
        />
        <h1>SCVSAR Response Tracker</h1>
        <div className="metrics">
          <span>Total Responders: {totalResponders}</span>
          <span>Average ETA: {avgMinutes()}</span>
        </div>
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
              <td>{entry.eta}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default App;