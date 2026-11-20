import { choosePlayer } from "./choosePlayer";
import { Html5Player } from "./Html5Player";
import { StreamEmbedPlayer } from "./StreamEmbedPlayer";
import type { PlayerOptions, PlayerProps } from "./types";

export function VideoPlayer({ options, ...props }: PlayerProps & { options: PlayerOptions }) {
  if (options.component) {
    const Custom = options.component;
    return <Custom {...props} />;
  }
  const choice = choosePlayer(props.minicode, options);
  if (choice.kind === "stream") return <StreamEmbedPlayer {...props} />;
  if (choice.kind === "html5") return <Html5Player {...props} src={choice.src} />;
  return (
    <div className="mcl-player mcl-player--none">
      <p>The video can&apos;t be embedded here.</p>
      {props.minicode.webUrl && (
        <a className="mcl-button" href={props.minicode.webUrl} target="_blank" rel="noreferrer">
          Watch in Stream
        </a>
      )}
    </div>
  );
}
