import type { PlayerProps } from "./types";
import { withStartTime } from "./streamUrl";

/**
 * Stream iframe player. Cross-origin, so it cannot be seeked programmatically; a seek reloads the iframe
 * with a new start time (`key` forces a fresh element so the same time twice also reloads).
 */
export function StreamEmbedPlayer({ minicode, seek, title }: PlayerProps) {
  if (!minicode.embedUrl) return null;
  return (
    <div className="mcl-player mcl-player--stream">
      <iframe
        key={seek.nonce}
        src={withStartTime(minicode.embedUrl, seek.seconds)}
        title={title}
        allow="autoplay; fullscreen; picture-in-picture"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  );
}
