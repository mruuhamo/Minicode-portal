import type { MinicodeDetail } from "../api/types";
import type { PlayerOptions } from "./types";

export type PlayerChoice = { kind: "stream" } | { kind: "html5"; src: string } | { kind: "link" };

export function choosePlayer(minicode: MinicodeDetail, options: PlayerOptions): PlayerChoice {
  const src = options.videoUrl?.(minicode) ?? null;
  switch (options.mode) {
    case "stream":
      return minicode.embedUrl ? { kind: "stream" } : { kind: "link" };
    case "html5":
      return src ? { kind: "html5", src } : { kind: "link" };
    default:
      if (minicode.embedUrl) return { kind: "stream" };
      return src ? { kind: "html5", src } : { kind: "link" };
  }
}
