import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ApiError, createApiClient, toQueryString } from "./client";
import { API, lastRequest, requests, server } from "../test/server";

describe("toQueryString", () => {
  it("joins multi-valued filters with commas and drops empty values", () => {
    expect(toQueryString({ tags: ["a", "b"], presenter: [], from: "", level: [200], top: 5, q: undefined })).toBe(
      "?tags=a%2Cb&level=200&top=5",
    );
    expect(toQueryString({})).toBe("");
  });
});

describe("createApiClient", () => {
  it("sends filters, paging and the bearer token", async () => {
    const api = createApiClient({ baseUrl: `${API}/`, getToken: async () => "tok-123" });
    await api.search({ q: "bicep registry", tags: ["devops-iac"], presenter: ["Aino Virtanen"], from: "2026-01-01", top: 12, skip: 12 });

    const url = lastRequest("/search")!;
    expect(url.searchParams.get("q")).toBe("bicep registry");
    expect(url.searchParams.get("tags")).toBe("devops-iac");
    expect(url.searchParams.get("presenter")).toBe("Aino Virtanen");
    expect(url.searchParams.get("from")).toBe("2026-01-01");
    expect(url.searchParams.get("skip")).toBe("12");
    expect(requests.at(-1)!.headers.get("authorization")).toBe("Bearer tok-123");
  });

  it("omits the Authorization header in dev mode", async () => {
    await createApiClient({ baseUrl: API }).listMinicodes({ sort: "+date", level: [200, 300] });
    expect(requests.at(-1)!.headers.has("authorization")).toBe(false);
    const url = lastRequest("/minicodes")!;
    expect(url.searchParams.get("sort")).toBe("+date");
    expect(url.searchParams.get("level")).toBe("200,300");
  });

  it("encodes ids and raises ApiError with the server message", async () => {
    let seen: URL | undefined;
    server.use(
      http.get(`${API}/minicodes/:id`, ({ request }) => {
        seen = new URL(request.url);
        return HttpResponse.json({ error: "invalid or expired token" }, { status: 401 });
      }),
    );
    const err = await createApiClient({ baseUrl: API })
      .getMinicode("a/b")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, message: "invalid or expired token" });
    expect(seen?.pathname).toBe("/api/minicodes/a%2Fb");
  });
});
