import { Fragment } from "react";

/**
 * Renders a search highlight fragment. The engine marks matches with `<em>...</em>`; everything else is plain text.
 * Splitting into React text nodes (no innerHTML) keeps transcript content from injecting markup.
 */
export function Highlight({ text }: { text: string }) {
  const parts = text.split(/(<em>.*?<\/em>)/gs);
  return (
    <>
      {parts.map((part, i) => {
        const m = /^<em>(.*)<\/em>$/s.exec(part);
        return m ? <mark key={i}>{m[1]}</mark> : <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}
