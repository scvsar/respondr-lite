import { getAccessToken } from "./auth/msalClient";
import { getLocalToken } from "./auth/localAuth";
import { apiUrl } from "./config";

async function getAuthHeader() {
  // Prefer MSAL/Entra tokens over local auth tokens
  const aad = await getAccessToken();
  if (aad) return { Authorization: `Bearer ${aad}` };
  
  const local = getLocalToken();
  if (local) return { Authorization: `Bearer ${local}` };
  
  return {};
}

export async function apiGet(path) {
  const headers = await getAuthHeader();
  const url = apiUrl(path);
  
  const res = await fetch(url, { headers });
  if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
          // Handle unauthorized - maybe redirect to login or throw specific error
          console.error("Unauthorized access");
      }
      throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}

export async function apiCall(path, options = {}) {
    const headers = await getAuthHeader();
    const url = apiUrl(path);
    
    const mergedOptions = {
        ...options,
        headers: {
            ...headers,
            ...options.headers
        }
    };

    const res = await fetch(url, mergedOptions);
    if (!res.ok) {
        throw new Error(`API error: ${res.status}`);
    }
    // Return response object so caller can handle 204 or other things, or json()
    return res;
}

export async function apiPost(path, body) {
    const headers = await getAuthHeader();
    headers["Content-Type"] = "application/json";
    const url = apiUrl(path);

    const res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body)
    });

    let data = null;
    try {
        data = await res.json();
    } catch {
        data = null;
    }

    if (!res.ok) {
        const message = data?.detail || data?.error || data?.message || `API error: ${res.status}`;
        throw new Error(message);
    }
    return data;
}
