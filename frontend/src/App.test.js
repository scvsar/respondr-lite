import { render, screen, waitFor } from '@testing-library/react';
import App from './App';

// Mock fetch API for all tests
beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      json: () => Promise.resolve([
        {
          name: "John Smith",
          text: "Taking SAR78, ETA 15 minutes",
          timestamp: "2025-08-01 12:00:00",
          vehicle: "SAR78",
          eta: "15 minutes"
        },
        {
          name: "Jane Doe",
          text: "Responding with POV, ETA 23:30",
          timestamp: "2025-08-01 12:05:00",
          vehicle: "POV",
          eta: "23:30"
        }
      ])
    })
  );
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('renders SCVSAR Response Tracker', () => {
  render(<App />);
  const headingElement = screen.getByText(/SCVSAR Response Tracker/i);
  expect(headingElement).toBeInTheDocument();
});

test('renders responder metrics', () => {
  render(<App />);
  const totalRespondersElement = screen.getByText(/Total Responders:/i);
  expect(totalRespondersElement).toBeInTheDocument();
  
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
  
  // Wait for the data to load
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith('/api/responders');
  });
  
  // Check that the responder data is displayed
  expect(await screen.findByText('John Smith')).toBeInTheDocument();
  expect(await screen.findByText('Jane Doe')).toBeInTheDocument();
  expect(await screen.findByText('SAR78')).toBeInTheDocument();
  expect(await screen.findByText('POV')).toBeInTheDocument();
  expect(await screen.findByText('15 minutes')).toBeInTheDocument();
  expect(await screen.findByText('23:30')).toBeInTheDocument();
});

test('shows correct metrics for responders', async () => {
  render(<App />);
  
  // Wait for data to load
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalled();
  });
  
  // Check that the metrics are displayed correctly (2 responders)
  const metricsText = await screen.findByText(/Total Responders: 2/i);
  expect(metricsText).toBeInTheDocument();
});
