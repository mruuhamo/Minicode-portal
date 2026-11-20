import type { MinicodeFilters, SortOrder } from "./api/types";

/** Listing state as kept in the URL query string, so searches and filters are shareable and survive reloads. */
export interface ListingState extends MinicodeFilters {
  q: string;
  sort: SortOrder;
  page: number;
}

export const PAGE_SIZE = 12;
const SORTS: SortOrder[] = ["date", "+date", "title", "level"];

const list = (p: URLSearchParams, key: string) =>
  p
    .getAll(key)
    .flatMap((v) => v.split(","))
    .map((v) => v.trim())
    .filter(Boolean);

export function readListingState(p: URLSearchParams): ListingState {
  const sort = p.get("sort") as SortOrder | null;
  const page = Number.parseInt(p.get("page") ?? "1", 10);
  return {
    q: p.get("q")?.trim() ?? "",
    tags: list(p, "tags"),
    presenter: list(p, "presenter"),
    contentType: list(p, "contentType"),
    level: list(p, "level")
      .map(Number)
      .filter((n) => Number.isFinite(n)),
    language: list(p, "language"),
    from: p.get("from") ?? undefined,
    to: p.get("to") ?? undefined,
    sort: sort && SORTS.includes(sort) ? sort : "date",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

export function writeListingState(s: Partial<ListingState>): URLSearchParams {
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  for (const key of ["tags", "presenter", "contentType", "level", "language"] as const) {
    const values = s[key];
    if (values?.length) p.set(key, values.join(","));
  }
  if (s.from) p.set("from", s.from);
  if (s.to) p.set("to", s.to);
  if (s.sort && s.sort !== "date") p.set("sort", s.sort);
  if (s.page && s.page > 1) p.set("page", String(s.page));
  return p;
}

export function hasFilters(s: ListingState): boolean {
  return Boolean(
    s.tags?.length || s.presenter?.length || s.contentType?.length || s.level?.length || s.language?.length || s.from || s.to,
  );
}
