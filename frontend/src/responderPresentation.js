export function responderStatus(entry) {
  const value = entry.arrival_status || entry.raw_status;
  if (['Responding', 'On Route', 'Arrived'].includes(value)) return 'Responding';
  if (['Cancelled', 'Not Responding', 'Available', 'Informational', 'Unknown'].includes(value)) return value;
  return String(entry.vehicle || '').toLowerCase() === 'not responding' ? 'Not Responding' : 'Unknown';
}

export function vehicleLabel(value) {
  if (!value) return 'Unknown';
  const compact = String(value).toUpperCase().replace(/\s+/g, '');
  if (compact === 'POV') return 'POV';
  const match = compact.match(/^SAR-?(\d+)$/);
  if (match) return `SAR-${match[1]}`;
  if (compact === 'UNKNOWN' || compact === 'NOTRESPONDING') return 'Unknown';
  return String(value);
}

export function parseTimestamp(value) {
  if (!value) return null;
  const normalized = typeof value === 'string' && value.includes(' ') && !value.includes('T') ? value.replace(' ', 'T') : value;
  const result = new Date(normalized);
  return Number.isNaN(result.getTime()) ? null : result;
}

export function localTimestamp(value) {
  const date = parseTimestamp(value);
  if (!date) return 'Unknown';
  const pad = n => String(n).padStart(2, '0');
  return `${pad(date.getMonth()+1)}/${pad(date.getDate())}/${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function minutesUntilArrival(entry, now = Date.now()) {
  const timestamp = parseTimestamp(entry.eta_timestamp_utc || entry.eta_timestamp);
  if (timestamp) return Math.ceil((timestamp.getTime() - now) / 60000);
  if (!entry.eta || entry.eta === 'Unknown') return null;
  return typeof entry.minutes_until_arrival === 'number' && Number.isFinite(entry.minutes_until_arrival)
    ? entry.minutes_until_arrival : null;
}
