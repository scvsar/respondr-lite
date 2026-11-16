import {parseTimestamp} from './responderPresentation';

const hours = {'1h':1,'6h':6,'12h':12,'24h':24,'3d':72,'7d':168};
export function timeWindowUrl(endpoint, range, customStart = '', now = Date.now()) {
  if (range === 'all') return endpoint;
  const since = range === 'custom' ? parseTimestamp(customStart)
    : hours[range] ? new Date(now - hours[range] * 3600000) : null;
  return since ? `${endpoint}?since=${since.toISOString()}` : null;
}
