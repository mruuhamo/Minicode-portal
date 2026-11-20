// Standalone app: the Learning section in a minimal shell. The portal embeds `LearningSection` from the library instead.
import { EventType, PublicClientApplication, type AuthenticationResult } from "@azure/msal-browser";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { learningReadScope } from "./auth/msal";
import { LearningSection, type LearningSectionProps } from "./LearningSection";
import type { PlayerMode } from "./player/types";

const env = import.meta.env;

async function authProps(): Promise<Partial<LearningSectionProps>> {
  if ((env.VITE_AUTH_MODE ?? "dev") !== "msal") return {}; // dev: backend runs with AUTH_MODE=dev, no tokens
  const clientId = env.VITE_ENTRA_CLIENT_ID;
  const tenantId = env.VITE_ENTRA_TENANT_ID;
  const scope = env.VITE_API_SCOPE || (env.VITE_API_CLIENT_ID ? learningReadScope(env.VITE_API_CLIENT_ID) : "");
  if (!clientId || !tenantId || !scope) {
    throw new Error("VITE_AUTH_MODE=msal needs VITE_ENTRA_CLIENT_ID, VITE_ENTRA_TENANT_ID and VITE_API_SCOPE");
  }
  const msalInstance = new PublicClientApplication({
    auth: {
      clientId,
      authority: `https://login.microsoftonline.com/${tenantId}`,
      redirectUri: window.location.origin + env.BASE_URL,
    },
    cache: { cacheLocation: "sessionStorage" },
  });
  await msalInstance.initialize();
  const redirect = await msalInstance.handleRedirectPromise();
  const account = redirect?.account ?? msalInstance.getAllAccounts()[0];
  if (account) msalInstance.setActiveAccount(account);
  msalInstance.addEventCallback((e) => {
    if (e.eventType === EventType.LOGIN_SUCCESS && e.payload) {
      msalInstance.setActiveAccount((e.payload as AuthenticationResult).account);
    }
  });
  return { msalInstance, apiScopes: [scope] };
}

const root = createRoot(document.getElementById("root")!);

authProps().then(
  (auth) =>
    root.render(
      <StrictMode>
        <div className="mcl-app">
          <header className="mcl-app__bar">
            <span className="mcl-app__brand">Learning</span>
          </header>
          <main className="mcl-app__main">
            <LearningSection
              {...auth}
              apiBaseUrl={env.VITE_API_BASE_URL || "/api"}
              basePath={env.BASE_URL}
              player={(env.VITE_PLAYER as PlayerMode | undefined) || "auto"}
              demoVideoUrl={env.VITE_DEMO_VIDEO_URL || undefined}
            />
          </main>
        </div>
      </StrictMode>,
    ),
  (e: unknown) => root.render(<pre role="alert">{String(e)}</pre>),
);
