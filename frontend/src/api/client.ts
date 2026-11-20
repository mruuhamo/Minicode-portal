import type {
  ListParams,
  MinicodeDetail,
  MinicodeFilters,
  MinicodeSummary,
  Page,
  SearchParams,
  SearchResponse,
  Taxonomy,
} from "./types";

/** Returns a bearer token for the API, or null to call without one (dev mode, AUTH_MODE=dev). */
export type TokenProvider = () => Promise<string | null>;

export interface ApiClientOptions {
  /** Base URL including the `/api` prefix, e.g. `https://func-minicode-prod.azurewebsites.net/api` or `/api`. */
  baseUrl: string;
  getToken?: TokenProvider;
  fetch?: typeof fetch;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface ApiClient {
  listMinicodes(params?: ListParams, signal?: AbortSignal): Promise<Page<MinicodeSummary>>;
  search(params: SearchParams, signal?: AbortSignal): Promise<SearchResponse>;
  getMinicode(id: string, signal?: AbortSignal): Promise<MinicodeDetail>;
  getTaxonomy(signal?: AbortSignal): Promise<Taxonomy>;
}

type QueryValue = string | number | undefined | (string | number)[];
type Query = Record<string, QueryValue>;

function filterQuery(f: MinicodeFilters): Query {
  return {
    tags: f.tags,
    presenter: f.presenter,
    contentType: f.contentType,
    level: f.level,
    language: f.language,
    from: f.from,
    to: f.to,
  };
}

/** Multi-valued filters are sent comma-separated (OR within a facet, AND across facets on the server). */
export function toQueryString(query: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      if (value.length) params.set(key, value.join(","));
    } else {
      params.set(key, String(value));
    }
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export function createApiClient({ baseUrl, getToken, fetch: fetchImpl }: ApiClientOptions): ApiClient {
  const base = baseUrl.replace(/\/+$/, "");
  const doFetch = fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init));

  async function get<T>(path: string, query: Query = {}, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = getToken ? await getToken() : null;
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await doFetch(`${base}${path}${toQueryString(query)}`, { headers, signal });
    if (!res.ok) {
      let message = res.statusText || `HTTP ${res.status}`;
      try {
        const body = (await res.json()) as { error?: string };
        if (body?.error) message = body.error;
      } catch {
        // non-JSON error body
      }
      throw new ApiError(res.status, message);
    }
    return (await res.json()) as T;
  }

  return {
    listMinicodes: (p = {}, signal) =>
      get("/minicodes", { ...filterQuery(p), sort: p.sort, top: p.top, skip: p.skip }, signal),
    search: (p, signal) => get("/search", { q: p.q, ...filterQuery(p), top: p.top, skip: p.skip }, signal),
    getMinicode: (id, signal) => get(`/minicodes/${encodeURIComponent(id)}`, {}, signal),
    getTaxonomy: (signal) => get("/taxonomy", {}, signal),
  };
}
