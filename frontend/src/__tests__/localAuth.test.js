import {vi} from 'vitest';
import {localLogin} from '../auth/localAuth';

const originalFunctionUrl = process.env.REACT_APP_FUNC_URL;
const originalFetch = global.fetch;
beforeEach(() => {
  localStorage.clear();
  global.fetch = vi.fn(async () => ({ok:true,json:async () => ({token:'synthetic-token'})}));
});
afterEach(() => {
  if (originalFunctionUrl === undefined) delete process.env.REACT_APP_FUNC_URL;
  else process.env.REACT_APP_FUNC_URL = originalFunctionUrl;
  global.fetch = originalFetch;
});

test('backend login sends the username field', async () => {
  delete process.env.REACT_APP_FUNC_URL;
  await localLogin('synthetic@example.test','synthetic-password');
  const [url, options] = global.fetch.mock.calls[0];
  expect(url).toContain('/api/auth/local/login');
  expect(JSON.parse(options.body)).toEqual({username:'synthetic@example.test',password:'synthetic-password'});
  expect(localStorage.getItem('local_jwt')).toBe('synthetic-token');
});

test('Function login sends the email field without a duplicate slash', async () => {
  process.env.REACT_APP_FUNC_URL = 'https://example.test/';
  await localLogin('synthetic@example.test','synthetic-password');
  const [url, options] = global.fetch.mock.calls[0];
  expect(url).toBe('https://example.test/api/local_login');
  expect(JSON.parse(options.body)).toEqual({email:'synthetic@example.test',password:'synthetic-password'});
});

test('a failed login cannot store a token', async () => {
  global.fetch.mockResolvedValue({ok:false,status:401,text:async () => 'Invalid credentials'});
  await expect(localLogin('synthetic@example.test','bad-password')).rejects.toThrow('Local login failed');
  expect(localStorage.getItem('local_jwt')).toBeNull();
});
