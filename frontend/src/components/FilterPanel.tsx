import type { FacetValue, Facets } from "../api/types";
import type { Labels } from "../format";
import type { ListingState } from "../listingState";

type MultiKey = "tags" | "contentType" | "level" | "presenter" | "language";

interface Group {
  key: MultiKey;
  facet: keyof Facets;
  legend: string;
  label: (value: string | number) => string;
}

export interface FilterPanelProps {
  state: ListingState;
  facets: Facets | undefined;
  labels: Labels;
  onChange: (next: Partial<ListingState>) => void;
  onClear: () => void;
}

export function FilterPanel({ state, facets, labels, onChange, onClear }: FilterPanelProps) {
  const groups: Group[] = [
    { key: "tags", facet: "topics", legend: "Topic", label: (v) => labels.topic(String(v)) },
    { key: "presenter", facet: "presenter", legend: "Presenter", label: String },
    { key: "contentType", facet: "contentType", legend: "Content type", label: (v) => labels.contentType(String(v)) },
    { key: "level", facet: "level", legend: "Level", label: (v) => labels.level(v) },
    { key: "language", facet: "language", legend: "Language", label: (v) => String(v).toUpperCase() },
  ];

  const toggle = (key: MultiKey, value: string | number, on: boolean) => {
    const current = (state[key] ?? []) as (string | number)[];
    const next = on ? [...current, value] : current.filter((v) => String(v) !== String(value));
    onChange({ [key]: next, page: 1 } as Partial<ListingState>);
  };

  return (
    <aside className="mcl-filters" aria-label="Filters">
      <div className="mcl-filters__header">
        <h2>Filters</h2>
        <button type="button" className="mcl-linkbutton" onClick={onClear}>
          Clear all
        </button>
      </div>
      {groups.map((g) => {
        const selected = ((state[g.key] ?? []) as (string | number)[]).map(String);
        const values = mergeSelected((facets?.[g.facet] ?? []) as FacetValue<string | number>[], selected);
        if (!values.length) return null;
        return (
          <fieldset key={g.key} className="mcl-facet">
            <legend>{g.legend}</legend>
            <ul>
              {values.map((v) => {
                const checked = selected.includes(String(v.value));
                return (
                  <li key={String(v.value)}>
                    <label>
                      <input
                        type="checkbox"
                        checked={checked}
                        aria-label={`${g.label(v.value)}, ${v.count} ${v.count === 1 ? "minicode" : "minicodes"}`}
                        onChange={(e) => toggle(g.key, g.key === "level" ? Number(v.value) : String(v.value), e.target.checked)}
                      />
                      <span className="mcl-facet__label">{g.label(v.value)}</span>
                      <span className="mcl-facet__count" aria-hidden="true">
                        {v.count}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </fieldset>
        );
      })}
      <fieldset className="mcl-facet mcl-facet--dates">
        <legend>Date</legend>
        <label>
          From
          <input type="date" value={state.from ?? ""} onChange={(e) => onChange({ from: e.target.value || undefined, page: 1 })} />
        </label>
        <label>
          To
          <input type="date" value={state.to ?? ""} onChange={(e) => onChange({ to: e.target.value || undefined, page: 1 })} />
        </label>
      </fieldset>
    </aside>
  );
}

/** Keeps selected values visible (count 0) even when the current result set has no matches for them. */
function mergeSelected(values: FacetValue<string | number>[], selected: string[]) {
  const seen = new Set(values.map((v) => String(v.value)));
  return [...values, ...selected.filter((s) => !seen.has(s)).map((s) => ({ value: s, count: 0 }))];
}
