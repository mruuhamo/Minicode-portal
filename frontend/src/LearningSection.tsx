import type { IPublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import { useMemo, type ReactNode } from "react";
import { BrowserRouter, Route, Routes, useInRouterContext } from "react-router";
import { createApiClient, type TokenProvider } from "./api/client";
import type { Taxonomy } from "./api/types";
import { AuthGate } from "./auth/AuthGate";
import { createMsalTokenProvider } from "./auth/msal";
import { LearningContext, type LearningContextValue } from "./context";
import { DetailPage } from "./pages/DetailPage";
import { ListingPage } from "./pages/ListingPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import type { PlayerMode, PlayerOptions } from "./player/types";
import "./styles.css";

export interface LearningSectionProps {
  /** Search API base URL including `/api`. Default `/api` (same origin or dev proxy). */
  apiBaseUrl?: string;
  /** URL path the section is mounted at, e.g. `/learning`. Default `/`. */
  basePath?: string;
  /**
   * The portal's MSAL instance (already `initialize()`d). When given, the section requires sign-in and
   * acquires API tokens for `apiScopes` with it. Omit it (and `getAccessToken`) for dev mode with AUTH_MODE=dev.
   */
  msalInstance?: IPublicClientApplication;
  /** Delegated scopes for the Search API, e.g. `["api://<api-client-id>/Learning.Read"]`. */
  apiScopes?: string[];
  /** Alternative to `msalInstance`: the portal supplies tokens itself. Takes precedence over `msalInstance`. */
  getAccessToken?: TokenProvider;
  /** Video player selection, or full player options (custom component, HTML5 source). Default `auto`. */
  player?: PlayerMode | PlayerOptions;
  /** HTML5 video used for every minicode when the Stream embed isn't available (local demo with mock data). */
  demoVideoUrl?: string;
  className?: string;
}

const normalizeBase = (basePath: string) => {
  const trimmed = basePath.replace(/\/+$/, "");
  return trimmed === "" ? "" : trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
};

function cached<T>(load: () => Promise<T>): () => Promise<T> {
  let promise: Promise<T> | undefined;
  return () => {
    promise ??= load().catch((e: unknown) => {
      promise = undefined; // retry on next use
      throw e;
    });
    return promise;
  };
}

/**
 * The Learning section: minicode listing with search and filters, and a detail page with video and jump-to-timestamp.
 *
 * Mount it either inside the portal's own React Router (a route like `/learning/*`; pass the same `basePath`), or
 * standalone, in which case it creates its own `BrowserRouter` with `basename={basePath}`.
 */
export function LearningSection({
  apiBaseUrl = "/api",
  basePath = "/",
  msalInstance,
  apiScopes = [],
  getAccessToken,
  player = "auto",
  demoVideoUrl,
  className,
}: LearningSectionProps) {
  const inRouter = useInRouterContext();
  const scopesKey = apiScopes.join(" ");

  const value = useMemo<LearningContextValue>(() => {
    const scopes = scopesKey ? scopesKey.split(" ") : [];
    const getToken = getAccessToken ?? (msalInstance ? createMsalTokenProvider(msalInstance, scopes) : undefined);
    const api = createApiClient({ baseUrl: apiBaseUrl, getToken });
    const options: PlayerOptions = typeof player === "string" ? { mode: player } : player;
    const playerOptions: PlayerOptions = demoVideoUrl && !options.videoUrl ? { ...options, videoUrl: () => demoVideoUrl } : options;
    return {
      api,
      root: inRouter ? normalizeBase(basePath) : "",
      player: playerOptions,
      taxonomy: cached<Taxonomy>(() => api.getTaxonomy()),
    };
  }, [apiBaseUrl, basePath, getAccessToken, msalInstance, scopesKey, player, demoVideoUrl, inRouter]);

  let content: ReactNode = (
    <LearningContext.Provider value={value}>
      <Routes>
        <Route index element={<ListingPage />} />
        <Route path="minicodes/:id" element={<DetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </LearningContext.Provider>
  );
  if (!inRouter) content = <BrowserRouter basename={normalizeBase(basePath) || "/"}>{content}</BrowserRouter>;
  if (msalInstance && !getAccessToken) {
    content = (
      <MsalProvider instance={msalInstance}>
        <AuthGate scopes={apiScopes}>{content}</AuthGate>
      </MsalProvider>
    );
  }

  return <div className={`mcl-root${className ? ` ${className}` : ""}`}>{content}</div>;
}
