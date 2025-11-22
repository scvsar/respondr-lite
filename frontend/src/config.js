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
  if (window.location.hostname.includes('azurestaticapps.net')) {
    // You'll need to set this based on your Container App URL
    // This could be configured via Azure Static Web Apps configuration
    return window.__API_BASE_URL__ || '';
  }
  
  // Fallback to relative URLs (same domain)
  return '';
};

export const API_BASE_URL = getApiBaseUrl();

// Helper function to build API URLs
export const apiUrl = (path) => {
  const baseUrl = API_BASE_URL;
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return baseUrl ? `${baseUrl}${cleanPath}` : cleanPath;
};

const config = { API_BASE_URL, apiUrl };
export default config;