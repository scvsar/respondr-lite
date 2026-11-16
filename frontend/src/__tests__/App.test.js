import {vi} from 'vitest';
import React from 'react';
// Mock react-router-dom primitives used by the app so tests don't depend on real routing
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
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

// Mock MSAL and Local Auth modules
vi.mock('../auth/msalClient', () => {
  return {
    getAccessToken: vi.fn().mockImplementation(() => {
      console.log("MOCK getAccessToken CALLED");
      return Promise.resolve('dummy.eyJuYW1lIjogIlRlc3QgVXNlciIsICJwcmVmZXJyZWRfdXNlcm5hbWUiOiAidGVzdEBleGFtcGxlLmNvbSJ9.dummy');
    }),
    msalInstance: {
      initialize: vi.fn().mockResolvedValue(),
      handleRedirectPromise: vi.fn().mockResolvedValue(null),
      getAllAccounts: vi.fn().mockReturnValue([{ username: 'test@example.com' }]),
      getActiveAccount: vi.fn().mockReturnValue({ username: 'test@example.com' }),
      setActiveAccount: vi.fn(),
      addEventCallback: vi.fn(),
      removeEventCallback: vi.fn(),
      logoutRedirect: vi.fn(),
    },
    initializeMsal: vi.fn().mockResolvedValue(),
  };
});

const mockLocalToken = 'local.eyJkaXNwbGF5X25hbWUiOiJUZXN0IFVzZXIiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJpc19hZG1pbiI6dHJ1ZSwiYXV0aF90eXBlIjoibG9jYWwifQ==.sig';

import { render, screen, waitFor, act, fireEvent, within } from '@testing-library/react';
import App from '../App';

// Mock fetch API for all tests
beforeEach(() => {
  global.fetch = vi.fn(async (url, opts) => {
    const u = typeof url === 'string' ? url : '';
    if (u.includes('/api/user')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ authenticated: true, email: 'test@example.com', name: 'Test User' }),
      };
    }
    if (u.includes('/api/config')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ geocities: { force_mode: false, enable_toggle: false } }),
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

  window.localStorage.setItem('local_jwt', mockLocalToken);
});

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
});

test('renders SCVSAR Response Tracker', async () => {
  await act(async () => {
    render(<App />);
  });
  const headingElement = screen.getByText(/SCVSAR Response Tracker/i);
  expect(headingElement).toBeInTheDocument();
});

test.each([null, {rows: []}, [null], [{name: {invalid: true}}]])('malformed current status shows an error without a blank dashboard: %p', async payload => {
  const originalFetch = global.fetch;
  global.fetch = vi.fn(async (url, options) => String(url).includes('/api/current-status')
    ? {ok:true,json:async () => payload} : originalFetch(url, options));
  await act(async () => { render(<App />); });
  fireEvent.click(screen.getByRole('button', {name:/Current Status/i}));
  expect(await screen.findByText('Error: Invalid responder response')).toBeInTheDocument();
  expect(screen.getByText(/SCVSAR Response Tracker/i)).toBeInTheDocument();
});

test('current status applies time changes, including empty ranges and all time', async () => {
  const originalFetch = global.fetch;
  global.fetch = vi.fn(async (url, options) => {
    if (String(url).includes('/api/current-status')) {
      const params = new URL(String(url), 'http://localhost').searchParams;
      const rows = params.has('since') ? [] : [{
        id: 'old', name: 'Older Synthetic Responder', text: 'Responding',
        arrival_status: 'Responding', vehicle: 'Unknown', eta: 'Unknown',
        timestamp: '2026-02-22T18:50:56Z',
      }];
      return { ok: true, json: async () => rows };
    }
    return originalFetch(url, options);
  });
  await act(async () => { render(<App />); });
  fireEvent.click(screen.getByRole('button', { name: /Current Status/i }));
  fireEvent.change(screen.getByTitle('Filter messages by time period'), { target: { value: '3d' } });
  await waitFor(() => {
    const calls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/current-status'));
    const params = new URL(calls[calls.length - 1][0], 'http://localhost').searchParams;
    const elapsed = Date.now() - Date.parse(params.get('since'));
    expect(elapsed).toBeGreaterThanOrEqual(3 * 86400000 - 2000);
    expect(elapsed).toBeLessThan(3 * 86400000 + 2000);
    expect(screen.queryByText('Older Synthetic Responder')).not.toBeInTheDocument();
  });
  fireEvent.change(screen.getByTitle('Filter messages by time period'), { target: { value: 'all' } });
  await waitFor(() => expect(screen.getByText('Older Synthetic Responder')).toBeInTheDocument());
  fireEvent.change(screen.getByTitle('Filter messages by time period'), { target: { value: '3d' } });
  await waitFor(() => expect(screen.queryByText('Older Synthetic Responder')).not.toBeInTheDocument());
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

test('unknown vehicle stays unknown even with a previous known vehicle', async () => {
  const originalFetch = global.fetch;
  global.fetch = vi.fn(async (url, options) => {
    if (String(url).includes('/api/responders')) return {ok:true, json:async () => [
      {id:'old',user_id:'user-1',name:'Synthetic User',text:'Earlier reply',vehicle:'POV',timestamp:'2026-01-01T00:00:00Z'},
      {id:'new',user_id:'user-1',name:'Synthetic User',text:'Vehicle is unknown',vehicle:'Unknown',timestamp:'2026-01-01T01:00:00Z'},
    ]};
    return originalFetch(url, options);
  });
  await act(async () => { render(<App />); });
  const row = (await screen.findByText('Vehicle is unknown')).closest('tr');
  expect(within(row).getAllByRole('cell')[4]).toHaveTextContent('Unknown');
});

test('late response from an old time filter cannot replace current data', async () => {
  let releaseOld;
  const oldResult = new Promise(resolve => { releaseOld = resolve; });
  const originalFetch = global.fetch;
  const newer = [{id:'new',name:'New Range Responder',text:'Responding',vehicle:'Unknown'}];
  global.fetch = vi.fn(async (url, options) => {
    if (String(url).includes('/api/responders')) {
      const rows = String(url).includes('since=') ? await oldResult : newer;
      return {ok:true,json:async () => rows};
    }
    return originalFetch(url, options);
  });
  await act(async () => { render(<App />); });
  fireEvent.change(screen.getByTitle('Filter messages by time period'), {target:{value:'all'}});
  await screen.findByText('New Range Responder');
  await act(async () => releaseOld([{id:'old',name:'Old Range Responder',text:'Old',vehicle:'Unknown'}]));
  expect(screen.getByText('New Range Responder')).toBeInTheDocument();
  expect(screen.queryByText('Old Range Responder')).not.toBeInTheDocument();
});

test('current status totals use latest statuses rather than older responding messages', async () => {
  const originalFetch = global.fetch;
  global.fetch = vi.fn(async (url, options) => {
    if (String(url).includes('/api/current-status')) return {ok:true,json:async () => [
      {id:'latest',user_id:'user-1',name:'Synthetic User',text:'Cannot respond',arrival_status:'Cancelled',vehicle:'Unknown',eta:'Unknown'},
    ]};
    return originalFetch(url, options);
  });
  await act(async () => { render(<App />); });
  fireEvent.click(screen.getByRole('button',{name:/Current Status/i}));
  await waitFor(() => {
    const card=screen.getByText('Responders',{exact:true}).closest('.stat-card-Responders');
    expect(within(card).getByText('0/1')).toBeInTheDocument();
    expect(screen.getByText('No responders match the filters')).toBeInTheDocument();
    expect(screen.getByRole('button',{name:/Current Status/i})).toHaveTextContent('0');
  });
});

test('calculates average ETA correctly', async () => {
  // Mock fetch for both user authentication and responder data
  global.fetch = vi.fn((url) => {
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
            arrival_status: 'Responding',
            name: 'Responder 1',
            text: 'On my way',
            vehicle: 'SAR1',
            eta: '10:30',
            minutes_until_arrival: 30,
            timestamp: '2023-01-01 10:00:00'
          },
          {
            id: '2', 
            arrival_status: 'Responding',
            name: 'Responder 2',
            text: 'Responding',
            vehicle: 'SAR2',
            eta: '10:45',
            minutes_until_arrival: 45,
            timestamp: '2023-01-01 10:00:00'
          },
          {
            id: '3',
            arrival_status: 'Responding',
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
