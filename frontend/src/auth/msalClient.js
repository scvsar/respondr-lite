import { PublicClientApplication } from "@azure/msal-browser";

// Support both naming conventions (AAD_... and AZURE_...)
const clientId = process.env.REACT_APP_AAD_CLIENT_ID || process.env.REACT_APP_AZURE_CLIENT_ID;
const tenantId = process.env.REACT_APP_AAD_TENANT_ID || process.env.REACT_APP_AZURE_TENANT_ID;
const apiScope = process.env.REACT_APP_AAD_API_SCOPE || process.env.REACT_APP_AZURE_SCOPES || "User.Read";

// Check if configuration is present
const isMsalConfigured = !!clientId && !!tenantId;

if (!isMsalConfigured) {
  console.warn("MSAL is not configured. Missing Client ID or Tenant ID in environment variables.");
}

export const msalInstance = new PublicClientApplication({
  auth: {
    clientId: clientId || "placeholder-client-id", // Prevent crash on init if missing
    authority: `https://login.microsoftonline.com/${tenantId || "common"}`,
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
    storeAuthStateInCookie: false,
  },
});

let isInitialized = false;
let initPromise = null;

export async function initializeMsal() {
    if (isInitialized) return;
    if (!initPromise) {
        initPromise = (async () => {
            await msalInstance.initialize();
            try {
                // Handle the redirect response after login
                const response = await msalInstance.handleRedirectPromise();
                if (response) {
                    console.log("Login successful via redirect", response);
                    msalInstance.setActiveAccount(response.account);
              } else {
                const existing = msalInstance.getAllAccounts();
                if (!msalInstance.getActiveAccount() && existing.length > 0) {
                  msalInstance.setActiveAccount(existing[0]);
                }
                }
            } catch (error) {
                console.error("Redirect handling failed", error);
            }
            isInitialized = true;
        })();
    }
    await initPromise;
}

export async function getAccessToken() {
  if (!isMsalConfigured) {
    console.warn("Cannot get access token: MSAL is not configured.");
    return null;
  }

  await initializeMsal();

  const accounts = msalInstance.getAllAccounts();
  if (accounts.length === 0) {
      return null;
  }

  // Prefer explicitly active account; fall back to first cached account.
  // This prevents accidentally using a stale token from a different user.
  let account = msalInstance.getActiveAccount();
  if (!account) {
    account = accounts[0];
    msalInstance.setActiveAccount(account);
  }
  
  const request = {
    scopes: [apiScope],
    account,
  };

  try {
    const result = await msalInstance.acquireTokenSilent(request);
    return result.accessToken;
  } catch (error) {
    console.warn("Silent token acquisition failed", error);
    // Do not try popup automatically - let the caller handle the login flow
    return null;
  }
}

export const msalConfig = {
    isConfigured: isMsalConfigured,
    scopes: [apiScope]
};
