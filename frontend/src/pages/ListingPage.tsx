import { useSearchParams } from "react-router";
import { ErrorMessage } from "../components/ErrorMessage";
import { FilterPanel } from "../components/FilterPanel";
import { MinicodeCard } from "../components/MinicodeCard";
import { Pagination } from "../components/Pagination";
import { SearchBox } from "../components/SearchBox";
import { useLearning } from "../context";
import { labelsFrom } from "../format";
import { useAsync } from "../hooks/useAsync";
import { useLabels } from "../hooks/useLabels";
import { hasFilters, PAGE_SIZE, readListingState, writeListingState, type ListingState } from "../listingState";
import type { SortOrder } from "../api/types";

const SORT_LABELS: Record<SortOrder, string> = {
  date: "Newest first",
  "+date": "Oldest first",
  title: "Title A-Z",
  level: "Level",
};

export function ListingPage() {
  const { api } = useLearning();
  const labels = useLabels() ?? labelsFrom(undefined);
  const [params, setParams] = useSearchParams();
  const state = readListingState(params);
  const key = writeListingState(state).toString();

  const result = useAsync(key, (signal) => {
    const common = {
      tags: state.tags,
      presenter: state.presenter,
      contentType: state.contentType,
      level: state.level,
      language: state.language,
      from: state.from,
      to: state.to,
      top: PAGE_SIZE,
      skip: (state.page - 1) * PAGE_SIZE,
    };
    return state.q ? api.search({ q: state.q, ...common }, signal) : api.listMinicodes({ ...common, sort: state.sort }, signal);
  });

  const update = (next: Partial<ListingState>) => setParams(writeListingState({ ...state, ...next }));
  const data = result.data;

  return (
    <div className="mcl-listing">
      <header className="mcl-listing__header">
        <h1>Minicodes</h1>
        <p className="mcl-lead">Internal tech talks and knowledge shares, searchable down to the transcript.</p>
        <SearchBox initial={state.q} onSearch={(q) => update({ q, page: 1 })} />
      </header>
      <div className="mcl-listing__body">
        <FilterPanel
          state={state}
          facets={data?.facets}
          labels={labels}
          onChange={update}
          onClear={() => setParams(writeListingState({ q: state.q, sort: state.sort }))}
        />
        <section className="mcl-results" aria-labelledby="mcl-results-heading" aria-busy={result.loading}>
          <div className="mcl-results__toolbar">
            <h2 id="mcl-results-heading" className="mcl-results__count" aria-live="polite">
              {result.loading
                ? "Loading..."
                : data
                  ? `${data.count} ${data.count === 1 ? "minicode" : "minicodes"}${state.q ? ` for "${state.q}"` : ""}`
                  : ""}
            </h2>
            {!state.q && (
              <label className="mcl-sort">
                Sort
                <select value={state.sort} onChange={(e) => update({ sort: e.target.value as SortOrder, page: 1 })}>
                  {Object.entries(SORT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {result.error && <ErrorMessage error={result.error} />}
          {data && data.items.length === 0 && (
            <p className="mcl-empty">
              No minicodes match{state.q ? ` "${state.q}"` : ""}
              {hasFilters(state) ? " with these filters" : ""}.
            </p>
          )}
          {data && (
            <ul className="mcl-cardlist">
              {data.items.map((item) => (
                <li key={item.id}>
                  <MinicodeCard item={item} labels={labels} />
                </li>
              ))}
            </ul>
          )}
          {data && <Pagination page={state.page} pageSize={PAGE_SIZE} count={data.count} onPage={(page) => update({ page })} />}
        </section>
      </div>
    </div>
  );
}
