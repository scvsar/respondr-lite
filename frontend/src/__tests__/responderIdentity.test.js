import { responderKey } from '../responderIdentity';

test('source identity survives a name change but remains scoped to a group', () => {
  const first = {user_id:'user-1',name:'Old Name',group_id:'group-1'};
  expect(responderKey(first)).toBe(responderKey({...first,name:'New Name'}));
  expect(responderKey(first)).not.toBe(responderKey({...first,user_id:'user-2'}));
  expect(responderKey(first)).not.toBe(responderKey({...first,group_id:'group-2'}));
});

test('server identity supports legacy records without source IDs', () => {
  expect(responderKey({name:'Old Name',responder_key:'server-key'})).toBe('server-key');
});
