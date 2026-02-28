import { apiUrl } from '../config';

export async function localLogin(email, password) {
  // The function URL should be configured in environment variables or derived
  // If REACT_APP_FUNC_URL is set, use it (Azure Functions)
  // Otherwise, use the backend API path (FastAPI)
  
    let url = apiUrl('/api/auth/local/login');
  if (process.env.REACT_APP_FUNC_URL) {
      url = `${process.env.REACT_APP_FUNC_URL}/api/local_login`;
  }

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: email, password })
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
