// Types mirroring the week 3 Search API (backend/minicode/api/routes.py, backend/minicode/search/service.py).

export interface MinicodeSummary {
  id: string;
  title: string;
  summary: string | null;
  presenter: string | null;
  date: string | null; // YYYY-MM-DD
  topics: string[];
  contentType: string | null;
  level: number | null;
  language: string | null;
  keywords: string[];
  webUrl: string | null;
  durationSeconds: number | null;
}

export interface Chapter {
  start: number;
  end: number;
  startLabel: string;
  speakers: string[];
  preview: string;
  url: string | null;
}

export interface MinicodeDetail extends MinicodeSummary {
  recordedAt: string | null;
  /** Stream (SharePoint) iframe player URL; null when the item has no listItemUniqueId. */
  embedUrl: string | null;
  transcriptSource: string | null;
  chunkCount: number | null;
  chapters: Chapter[];
}

export interface ChunkHit {
  chunkId: string;
  start: number;
  end: number;
  startLabel: string;
  speakers: string[];
  /** Fragments with `<em>` markers from the search engine; render with <Highlight>, never as raw HTML. */
  highlights: string[];
  text: string | null;
  url: string | null;
}

export interface SearchItem extends MinicodeSummary {
  score: number;
  matchedSummary: boolean;
  hits: ChunkHit[];
}

export interface FacetValue<T = string> {
  value: T;
  count: number;
}

export interface Facets {
  topics?: FacetValue[];
  contentType?: FacetValue[];
  level?: FacetValue<number>[];
  presenter?: FacetValue[];
  language?: FacetValue[];
  year?: FacetValue<number | string>[];
}

export interface Page<T> {
  items: T[];
  count: number;
  top: number;
  skip: number;
  facets: Facets;
}

export interface SearchResponse extends Page<SearchItem> {
  query: string;
}

export interface TaxonomyTag {
  id: string;
  label: string;
}

export interface Taxonomy {
  topic: TaxonomyTag[];
  content_type: TaxonomyTag[];
  level: TaxonomyTag[];
  version: string | number;
}

export type SortOrder = "date" | "+date" | "title" | "level";

export interface MinicodeFilters {
  tags?: string[];
  presenter?: string[];
  contentType?: string[];
  level?: number[];
  language?: string[];
  from?: string;
  to?: string;
}

export interface ListParams extends MinicodeFilters {
  sort?: SortOrder;
  top?: number;
  skip?: number;
}

export interface SearchParams extends MinicodeFilters {
  q: string;
  top?: number;
  skip?: number;
}
