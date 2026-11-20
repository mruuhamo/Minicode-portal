import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ErrorMessage } from "../components/ErrorMessage";
import { TagList } from "../components/TagList";
import { useLearning, useLinks } from "../context";
import { formatDate, formatDuration, formatTimestamp, labelsFrom } from "../format";
import { useAsync } from "../hooks/useAsync";
import { useLabels } from "../hooks/useLabels";
import type { Seek } from "../player/types";
import { VideoPlayer } from "../player/VideoPlayer";

export function DetailPage() {
  const { id = "" } = useParams();
  const { api, player } = useLearning();
  const links = useLinks();
  const labels = useLabels() ?? labelsFrom(undefined);
  const [params, setParams] = useSearchParams();
  const t = Math.max(0, Number.parseInt(params.get("t") ?? "0", 10) || 0);

  // nonce 0 = initial position from the URL (no autoplay); every chapter click bumps it so seeking always happens
  const [seek, setSeek] = useState<Seek>({ seconds: t, nonce: 0 });
  const [prevT, setPrevT] = useState(t);
  if (t !== prevT) {
    setPrevT(t);
    if (t !== seek.seconds) setSeek({ seconds: t, nonce: seek.nonce + 1 });
  }

  const { data, error, loading } = useAsync(`minicode:${id}`, (signal) => api.getMinicode(id, signal));

  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (data) headingRef.current?.focus(); // move focus for screen readers after client-side navigation
  }, [data]);

  const playFrom = (seconds: number) => {
    setSeek((s) => ({ seconds, nonce: s.nonce + 1 }));
    setPrevT(Math.floor(seconds));
    setParams((p) => {
      const next = new URLSearchParams(p);
      next.set("t", String(Math.floor(seconds)));
      return next;
    }, { replace: true });
  };

  return (
    <div className="mcl-detail">
      <nav aria-label="Breadcrumb" className="mcl-breadcrumb">
        <Link to={links.listing()}>← All minicodes</Link>
      </nav>
      {loading && (
        <p className="mcl-status" role="status">
          Loading...
        </p>
      )}
      {error && <ErrorMessage error={error} />}
      {data && (
        <article aria-labelledby="mcl-detail-title">
          <h1 id="mcl-detail-title" ref={headingRef} tabIndex={-1}>
            {data.title}
          </h1>
          <p className="mcl-card__meta">
            {[data.presenter, formatDate(data.date), formatDuration(data.durationSeconds)].filter(Boolean).join(" · ")}
          </p>
          <div className="mcl-detail__layout">
            <div className="mcl-detail__main">
              <VideoPlayer options={player} minicode={data} seek={seek} title={`Video: ${data.title}`} />
              {seek.seconds > 0 && (
                <p className="mcl-detail__position" aria-live="polite">
                  Starting at {formatTimestamp(seek.seconds)}
                </p>
              )}
              <section aria-labelledby="mcl-summary-heading">
                <h2 id="mcl-summary-heading">Summary</h2>
                <p>{data.summary ?? "No summary yet."}</p>
              </section>
              <TagList item={data} labels={labels} />
              {data.webUrl && (
                <p>
                  <a href={data.webUrl} target="_blank" rel="noreferrer">
                    Open in Stream
                  </a>
                </p>
              )}
            </div>
            {data.chapters.length > 0 && (
              <section className="mcl-chapters" aria-labelledby="mcl-chapters-heading">
                <h2 id="mcl-chapters-heading">Transcript sections</h2>
                <ol>
                  {data.chapters.map((c) => {
                    const active = seek.seconds >= c.start && seek.seconds < c.end;
                    return (
                      <li key={c.start}>
                        <button
                          type="button"
                          className={`mcl-chapter${active ? " mcl-chapter--active" : ""}`}
                          aria-current={active ? "true" : undefined}
                          onClick={() => playFrom(c.start)}
                        >
                          <span className="mcl-hit__time">▶ {c.startLabel}</span>
                          {c.speakers.length > 0 && <span className="mcl-hit__speakers">{c.speakers.join(", ")}</span>}
                          <span className="mcl-chapter__preview">{c.preview}</span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </section>
            )}
          </div>
        </article>
      )}
    </div>
  );
}
