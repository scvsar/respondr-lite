import React from 'react';
// Mock react-router-dom to avoid module resolution issues during tests
jest.mock('react-router-dom', () => ({
  BrowserRouter: ({ children }) => <>{children}</>,
  Routes: ({ children }) => <>{children}</>,
  Route: ({ element }) => element,
}), { virtual: true });
import { render, screen, waitFor, act } from '@testing-library/react';
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

test('renders SCVSAR Response Tracker', async () => {
  await act(async () => {
    render(<App />);
  });
  const headingElement = screen.getByText(/SCVSAR Response Tracker/i);
  expect(headingElement).toBeInTheDocument();
});

test('renders responder stats', async () => {
  await act(async () => {
    render(<App />);
  });
  
  // Wait for the data to load and metrics to appear
  await waitFor(() => {
    expect(screen.getAllByText(/Responders/i).length).toBeGreaterThan(0);
  }, { timeout: 3000 });

  const avgEtaElement = screen.getByText(/Avg ETA/i);
  expect(avgEtaElement).toBeInTheDocument();
});

test('renders table headers', async () => {
  await act(async () => {
    render(<App />);
  });
  expect(screen.getByRole('button', { name: /Time/i })).toBeInTheDocument();
  expect(screen.getByText('Name')).toBeInTheDocument();
  expect(screen.getByText('Message')).toBeInTheDocument();
  expect(screen.getByText('Vehicle')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /ETA/i })).toBeInTheDocument();
});

test('fetches and displays responder data', async () => {
  await act(async () => {
    render(<App />);
  });
  
  // Wait for the fetch to be called and data to load
  await waitFor(() => {
  expect(global.fetch).toHaveBeenCalledWith('/api/responders', expect.anything());
  }, { timeout: 3000 });
  
  // Check that the responder data is displayed
  await waitFor(() => {
    expect(screen.getByText('John Smith')).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getAllByText('SAR-78').length).toBeGreaterThan(0);
  expect(screen.getAllByText('POV').length).toBeGreaterThan(0);
  }, { timeout: 3000 });
});
