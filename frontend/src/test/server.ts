import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { detail, listPage, searchPage, taxonomy } from "./fixtures";

export const API = "http://api.test/api";

/** Requests seen by the default handlers, for asserting query strings and headers. */
export const requests: Request[] = [];

export const handlers = [
  http.get(`${API}/taxonomy`, ({ request }) => {
    requests.push(request);
    return HttpResponse.json(taxonomy);
  }),
  http.get(`${API}/minicodes`, ({ request }) => {
    requests.push(request);
    return HttpResponse.json(listPage);
  }),
  http.get(`${API}/search`, ({ request }) => {
    requests.push(request);
    return HttpResponse.json(searchPage);
  }),
  http.get(`${API}/minicodes/:id`, ({ request, params }) => {
    requests.push(request);
    if (params.id !== detail.id) return HttpResponse.json({ error: "not found" }, { status: 404 });
    return HttpResponse.json(detail);
  }),
];

export const server = setupServer(...handlers);

export function lastRequest(path: string): URL | undefined {
  const hit = [...requests].reverse().find((r) => new URL(r.url).pathname === `/api${path}`);
  return hit ? new URL(hit.url) : undefined;
}
