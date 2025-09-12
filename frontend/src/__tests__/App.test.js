import React from 'react';
// Mock react-router-dom primitives used by the app so tests don't depend on real routing
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('react-router-dom');
  const Mocked = {
    ...actual,
    BrowserRouter: ({ children }) => <>{children}</>,
    Routes: ({ children }) => <>{children}</>,
    Route: (props) => {
      const { element, path } = props || {};
      // Simulate route matching at '/'
      if (!path || path === '/') return element || null;
      return null;
    },
    Navigate: ({ children }) => <>{children || null}</>,
    useLocation: () => ({ pathname: '/' }),
  };
  return Mocked;
});
import { render, screen, waitFor, act } from '@testing-library/react';
import App from '../App';

// Mock fetch API for all tests
beforeEach(() => {
  global.fetch = jest.fn(async (url, opts) => {
    const u = typeof url === 'string' ? url : '';
    if (u.includes('/api/user')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ authenticated: true, email: 'test@example.com', name: 'Test User' }),
      };
    }
    if (u.includes('/api/current-status')) {
      // Mirror responder data in current status so the default tab has content
      return {
        ok: true,
        status: 200,
        json: async () => ([
          {
            id: 'u1',
            name: 'John Smith',
            text: 'Taking SAR78, ETA 15 minutes',
            timestamp: '2025-08-01 12:00:00',
            vehicle: 'SAR78',
            eta: '15 minutes',
            eta_timestamp: '2025-08-01 12:15:00',
            minutes_until_arrival: 15,
          },
          {
            id: 'u2',
            name: 'Jane Doe',
            text: 'Responding with POV, ETA 23:30',
            timestamp: '2025-08-01 12:05:00',
            vehicle: 'POV',
            eta: '23:30',
            eta_timestamp: '2025-08-01 23:30:00',
            minutes_until_arrival: 690,
          },
        ]),
      };
    }
    if (u.includes('/api/responders')) {
      return {
        ok: true,
        status: 200,
        json: async () => ([
          {
            name: 'John Smith',
            text: 'Taking SAR78, ETA 15 minutes',
            timestamp: '2025-08-01 12:00:00',
            vehicle: 'SAR78',
            eta: '15 minutes',
            eta_timestamp: '2025-08-01 12:15:00',
            minutes_until_arrival: 15,
          },
          {
            name: 'Jane Doe',
            text: 'Responding with POV, ETA 23:30',
            timestamp: '2025-08-01 12:05:00',
            vehicle: 'POV',
            eta: '23:30',
            eta_timestamp: '2025-08-01 23:30:00',
            minutes_until_arrival: 690,
          },
        ]),
      };
    }
    // Default OK empty response for any other endpoints the app might touch in tests
    return { ok: true, status: 200, json: async () => ({}) };
  });
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

test('calculates average ETA correctly', async () => {
  // Mock fetch for both user authentication and responder data
  global.fetch = jest.fn((url) => {
    if (url.includes('/api/user')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          authenticated: true,
          email: 'test@scvsar.org',
          name: 'Test User'
        })
      });
    }
    if (url.includes('/api/responders')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
          {
            id: '1',
            name: 'Responder 1',
            text: 'On my way',
            vehicle: 'SAR1',
            eta: '10:30',
            minutes_until_arrival: 30,
            timestamp: '2023-01-01 10:00:00'
          },
          {
            id: '2', 
            name: 'Responder 2',
            text: 'Responding',
            vehicle: 'SAR2',
            eta: '10:45',
            minutes_until_arrival: 45,
            timestamp: '2023-01-01 10:00:00'
          },
          {
            id: '3',
            name: 'Responder 3', 
            text: 'Already there',
            vehicle: 'SAR3',
            eta: '09:30',
            minutes_until_arrival: -30, // Negative = already arrived
            timestamp: '2023-01-01 10:00:00'
          }
        ])
      });
    }
    if (url === '/api/config') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          geocities: { force_mode: false, enable_toggle: false }
        })
      });
    }
    return Promise.reject(new Error('Unknown URL'));
  });

  await act(async () => {
    render(<App />);
  });

  // Wait for data to load
  await waitFor(() => {
    expect(screen.getByText('Responder 1')).toBeInTheDocument();
  });

  // Average should be (30 + 45) / 2 = 37.5, rounded to 38 minutes = 0h 38m
  // Should exclude the negative value (-30)
  await waitFor(() => {
    expect(screen.getByText('0h 38m')).toBeInTheDocument();
  });

  global.fetch.mockRestore();
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
    // The URL might have query parameters due to time filtering, so check if any call includes '/api/responders'
    const responderCalls = global.fetch.mock.calls.filter(call => 
      call[0] && call[0].toString().includes('/api/responders')
    );
    expect(responderCalls.length).toBeGreaterThan(0);
  }, { timeout: 3000 });
  
  // Check that the responder data is displayed
  await waitFor(() => {
    expect(screen.getByText('John Smith')).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getAllByText('SAR-78').length).toBeGreaterThan(0);
  expect(screen.getAllByText('POV').length).toBeGreaterThan(0);
  }, { timeout: 3000 });
});
