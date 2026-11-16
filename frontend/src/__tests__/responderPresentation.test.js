import {responderStatus,vehicleLabel,localTimestamp,minutesUntilArrival} from '../responderPresentation';

test('vehicle evidence alone cannot imply a response',()=>{
  expect(responderStatus({vehicle:'SAR-7'})).toBe('Unknown');
  expect(responderStatus({arrival_status:'Cancelled',vehicle:'SAR-7'})).toBe('Cancelled');
  expect(responderStatus({arrival_status:'Responding',vehicle:'Unknown'})).toBe('Responding');
});

test('vehicle formatting does not extract an invented SAR number from other text',()=>{
  expect(vehicleLabel('SAR 7')).toBe('SAR-7');
  expect(vehicleLabel('Unknown')).toBe('Unknown');
  expect(vehicleLabel('Unknown SAR 7?')).toBe('Unknown SAR 7?');
});

test('mobile time formatting converts timezone offsets rather than stripping them',()=>{
  const value='2026-01-01T12:00:00+02:00';
  const expected=new Date(value);
  const pad=n=>String(n).padStart(2,'0');
  expect(localTimestamp(value)).toContain(`${pad(expected.getHours())}:${pad(expected.getMinutes())}:00`);
});

test('remaining ETA uses the timestamp rather than an obsolete cached duration',()=>{
  const now=Date.parse('2026-01-01T10:00:00Z');
  expect(minutesUntilArrival({eta_timestamp_utc:'2026-01-01T10:10:00Z',minutes_until_arrival:90},now)).toBe(10);
  expect(minutesUntilArrival({eta_timestamp_utc:'2026-01-01T09:55:00Z',minutes_until_arrival:90},now)).toBe(-5);
  expect(minutesUntilArrival({eta:'Unknown',minutes_until_arrival:90},now)).toBeNull();
});
