import { Link } from "react-router";
import type { MinicodeSummary } from "../api/types";
import { useLinks } from "../context";
import type { Labels } from "../format";
import { writeListingState } from "../listingState";

/** Topic, content type and level chips; each links to the listing filtered by that value. */
export function TagList({ item, labels }: { item: MinicodeSummary; labels: Labels }) {
  const links = useLinks();
  const to = (q: Parameters<typeof writeListingState>[0]) => links.listing(`?${writeListingState(q).toString()}`);

  return (
    <ul className="mcl-tags" aria-label="Tags">
      {item.topics.map((t) => (
        <li key={t}>
          <Link className="mcl-tag mcl-tag--topic" to={to({ tags: [t] })}>
            {labels.topic(t)}
          </Link>
        </li>
      ))}
      {item.contentType && (
        <li>
          <Link className="mcl-tag mcl-tag--type" to={to({ contentType: [item.contentType] })}>
            {labels.contentType(item.contentType)}
          </Link>
        </li>
      )}
      {item.level != null && (
        <li>
          <Link className="mcl-tag mcl-tag--level" to={to({ level: [item.level] })}>
            Level {labels.level(item.level)}
          </Link>
        </li>
      )}
    </ul>
  );
}
