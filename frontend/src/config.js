// API configuration for frontend
const getApiBaseUrl = () => {
  // If running in development with CRA dev server
  if (process.env.NODE_ENV === 'development') {
    return ''; // Use proxy configuration
  }
  
  // If REACT_APP_API_URL is set, use it
  if (process.env.REACT_APP_API_URL) {
    return process.env.REACT_APP_API_URL;
  }
  
  // For Static Web Apps, try to detect the Container App URL
  // This could be set via staticwebapp.config.json or environment variables
  if (typeof window !== 'undefined' && window.location.hostname.includes('azurestaticapps.net')) {
    // Allow runtime override injected by hosting environment
    if (window.__API_BASE_URL__) {
      return window.__API_BASE_URL__;
    }
  }
  
  // Fallback to relative URLs (same domain)
  return '';
};

export const API_BASE_URL = getApiBaseUrl();

const parseBooleanEnv = (value) => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  return null;
};

// Build-time UI toggle for local auth availability.
// - true/false: trust static flag (no backend check required for visibility decisions)
// - unset/invalid: fall back to runtime API check
export const LOCAL_AUTH_UI_ENABLED = parseBooleanEnv(process.env.REACT_APP_ENABLE_LOCAL_AUTH);

// Helper function to build API URLs
export const apiUrl = (path) => {
  const baseUrl = API_BASE_URL;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return baseUrl ? `${baseUrl}${cleanPath}` : cleanPath;
};

const config = { API_BASE_URL, apiUrl };
export default config;