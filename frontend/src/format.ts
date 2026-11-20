import type { Taxonomy } from "./api/types";

export function formatDuration(seconds: number | null | undefined): string | null {
  if (!seconds || seconds <= 0) return null;
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
}

export function formatTimestamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatDate(date: string | null | undefined): string | null {
  if (!date) return null;
  const d = new Date(`${date.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export interface Labels {
  topic: (id: string) => string;
  contentType: (id: string) => string;
  level: (id: number | string) => string;
}

function lookup(tags: { id: string; label: string }[] | undefined) {
  const map = new Map((tags ?? []).map((t) => [t.id, t.label]));
  return (id: string | number) => map.get(String(id)) ?? String(id);
}

export function labelsFrom(taxonomy: Taxonomy | undefined): Labels {
  const level = lookup(taxonomy?.level);
  return {
    topic: lookup(taxonomy?.topic),
    contentType: lookup(taxonomy?.content_type),
    // "200 - Intermediate: familiar with the basics" -> "200 Intermediate"
    level: (id) => level(id).replace(/^(\d+)\s*-\s*([^:]+).*$/, "$1 $2"),
  };
}
