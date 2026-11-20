import {
  InteractionRequiredAuthError,
  type AccountInfo,
  type IPublicClientApplication,
} from "@azure/msal-browser";
import type { TokenProvider } from "../api/client";

/** Default delegated scope of the backend API app registration (`minicode-api-<env>`). */
export const learningReadScope = (apiClientId: string) => `api://${apiClientId}/Learning.Read`;

export function activeAccount(instance: IPublicClientApplication): AccountInfo | null {
  return instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null;
}

/**
 * Silent token acquisition for the Search API. When consent or a fresh sign-in is needed, it falls back to a redirect
 * (popups are often blocked inside portals). The promise rejects so the caller shows an error until the redirect lands.
 */
export function createMsalTokenProvider(instance: IPublicClientApplication, scopes: string[]): TokenProvider {
  return async () => {
    const account = activeAccount(instance);
    if (!account) {
      await instance.acquireTokenRedirect({ scopes });
      throw new Error("Signing in...");
    }
    try {
      const result = await instance.acquireTokenSilent({ scopes, account });
      return result.accessToken;
    } catch (e) {
      if (e instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ scopes, account });
      }
      throw e;
    }
  };
}
