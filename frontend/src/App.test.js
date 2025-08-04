import { render, screen, waitFor } from '@testing-library/react';
import App from './App';

// Mock fetch API for all tests
beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve([
        {
          name: "John Smith",
          text: "Taking SAR78, ETA 15 minutes",
          timestamp: "2025-08-01 12:00:00",
          vehicle: "SAR78",
          eta: "15 minutes",
          eta_timestamp: "2025-08-01 12:15:00",
          minutes_until_arrival: 15
        },
        {
          name: "Jane Doe",
          text: "Responding with POV, ETA 23:30",
          timestamp: "2025-08-01 12:05:00",
          vehicle: "POV",
          eta: "23:30",
          eta_timestamp: "2025-08-01 23:30:00",
          minutes_until_arrival: 690
        }
      ])
    })
  );
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.clearAllTimers();
  jest.useRealTimers();
});

test('renders SCVSAR Response Tracker', () => {
  render(<App />);
  const headingElement = screen.getByText(/SCVSAR Response Tracker/i);
  expect(headingElement).toBeInTheDocument();
});

test('renders responder metrics', async () => {
  render(<App />);
  
  // Wait for the data to load and metrics to appear
  await waitFor(() => {
    expect(screen.getByText(/Total Responders:/i)).toBeInTheDocument();
  }, { timeout: 3000 });
  
  const avgEtaElement = screen.getByText(/Average ETA:/i);
  expect(avgEtaElement).toBeInTheDocument();
});

test('renders table headers', () => {
  render(<App />);
  expect(screen.getByText('Time')).toBeInTheDocument();
  expect(screen.getByText('Name')).toBeInTheDocument();
  expect(screen.getByText('Message')).toBeInTheDocument();
  expect(screen.getByText('Vehicle')).toBeInTheDocument();
  expect(screen.getByText('ETA')).toBeInTheDocument();
});

test('fetches and displays responder data', async () => {
  render(<App />);
  
  // Wait for the fetch to be called and data to load
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith('/api/responders');
  }, { timeout: 3000 });
  
  // Check that the responder data is displayed
  await waitFor(() => {
    expect(screen.getByText('John Smith')).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('SAR78')).toBeInTheDocument();
    expect(screen.getByText('POV')).toBeInTheDocument();
  }, { timeout: 3000 });
});

test('shows correct metrics for responders', async () => {
  render(<App />);
  
  // Wait for data to load and metrics to appear
  await waitFor(() => {
    expect(screen.getByText(/Total Responders: 2/i)).toBeInTheDocument();
  }, { timeout: 3000 });
});
