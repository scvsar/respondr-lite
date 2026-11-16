const textFields = ['name', 'text', 'team', 'vehicle', 'arrival_status', 'raw_status', 'eta', 'responder_key'];
const scalarFields = ['id', 'user_id', 'sender_id', 'group_id', 'timestamp', 'timestamp_utc', 'eta_timestamp', 'eta_timestamp_utc'];

export function validateResponderData(value) {
  const validRow = row => row && typeof row === 'object' && !Array.isArray(row)
    && textFields.every(field => row[field] == null || typeof row[field] === 'string')
    && scalarFields.every(field => row[field] == null || typeof row[field] === 'string'
      || (typeof row[field] === 'number' && Number.isFinite(row[field])));
  if (!Array.isArray(value) || !value.every(validRow)) {
    throw new Error('Invalid responder response');
  }
  return value;
}
