import { Link } from "react-router";
import type { MinicodeSummary, SearchItem } from "../api/types";
import { useLinks } from "../context";
import { formatDate, formatDuration, type Labels } from "../format";
import { Highlight } from "./Highlight";
import { TagList } from "./TagList";

export function MinicodeCard({ item, labels }: { item: MinicodeSummary | SearchItem; labels: Labels }) {
  const links = useLinks();
  const hits = "hits" in item ? item.hits : [];
  const meta = [item.presenter, formatDate(item.date), formatDuration(item.durationSeconds)].filter(Boolean);

  return (
    <article className="mcl-card" aria-labelledby={`mcl-card-${item.id}`}>
      <h3 id={`mcl-card-${item.id}`} className="mcl-card__title">
        <Link to={links.detail(item.id)}>{item.title}</Link>
      </h3>
      {meta.length > 0 && <p className="mcl-card__meta">{meta.join(" · ")}</p>}
      {item.summary && <p className="mcl-card__summary">{item.summary}</p>}
      <TagList item={item} labels={labels} />
      {hits.length > 0 && (
        <div className="mcl-hits">
          <h4 className="mcl-hits__title">Matches in the transcript</h4>
          <ul>
            {hits.map((hit) => (
              <li key={hit.chunkId}>
                <Link
                  className="mcl-hit"
                  to={links.detail(item.id, hit.start)}
                  aria-label={`Play from ${hit.startLabel}: ${stripTags(hit.highlights[0] ?? hit.text ?? "")}`}
                >
                  <span className="mcl-hit__time">▶ {hit.startLabel}</span>
                  {hit.speakers.length > 0 && <span className="mcl-hit__speakers">{hit.speakers.join(", ")}</span>}
                  <span className="mcl-hit__text">
                    {hit.highlights.length ? (
                      hit.highlights.map((h, i) => (
                        <span key={i} className="mcl-hit__fragment">
                          <Highlight text={h} />
                        </span>
                      ))
                    ) : (
                      hit.text
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

const stripTags = (s: string) => s.replace(/<\/?em>/g, "");
