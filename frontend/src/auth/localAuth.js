import { apiUrl } from '../config';

export async function localLogin(email, password) {
  const functionUrl = (process.env.REACT_APP_FUNC_URL || '').trim().replace(/\/+$/, '');
  const url = functionUrl ? `${functionUrl}/api/local_login` : apiUrl('/api/auth/local/login');
  const credentials = functionUrl ? {email, password} : {username: email, password};

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials)
  });

  if (!resp.ok) {
      const errorText = await resp.text();
      throw new Error(`Local login failed: ${resp.status} ${errorText}`);
  }

  const data = await resp.json();
  const token = data.token;
  
  if (!token) {
      throw new Error("Login successful but no token received");
  }

  window.localStorage.setItem("local_jwt", token);
  return token;
}

export function getLocalToken() {
    return window.localStorage.getItem("local_jwt");
}

export function logoutLocal() {
    window.localStorage.removeItem("local_jwt");
}
