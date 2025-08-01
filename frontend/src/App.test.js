import { render, screen } from '@testing-library/react';
import App from './App';

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
