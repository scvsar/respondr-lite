export const responderKey = (entry) => {
  if (entry.responder_key) return entry.responder_key;
  const group = String(entry.group_id || 'unknown');
  const user = entry.user_id || entry.sender_id;
  if (user) return JSON.stringify([group, 'user', String(user)]);
  const name = String(entry.name || '').trim().toLowerCase();
  return JSON.stringify([group, name ? 'name' : 'message', name || String(entry.id || '')]);
};
