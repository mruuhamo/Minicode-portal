import type { ComponentType } from "react";
import type { MinicodeDetail } from "../api/types";

/**
 * A seek request. `nonce` changes on every request so seeking to the same time twice still seeks
 * (for example, clicking the same chapter again after scrolling the video).
 */
export interface Seek {
  seconds: number;
  nonce: number;
}

export interface PlayerProps {
  minicode: MinicodeDetail;
  seek: Seek;
  /** Accessible name for the player region. */
  title: string;
}

export type PlayerComponent = ComponentType<PlayerProps>;

/**
 * - `auto`: Stream embed when the API returns an `embedUrl`, otherwise the HTML5 player when a `videoUrl` is available,
 *   otherwise a link out to Stream.
 * - `stream`: always the Stream iframe (falls back to a link out when there is no embedUrl).
 * - `html5`: always a <video> element. Used for the local demo with mock data, where SharePoint URLs do not exist.
 */
export type PlayerMode = "auto" | "stream" | "html5";

export interface PlayerOptions {
  mode: PlayerMode;
  /** Playable URL for the HTML5 player. Mock data has no real video, so the demo uses one sample clip for every item. */
  videoUrl?: (minicode: MinicodeDetail) => string | null | undefined;
  /** Replace the built-in players entirely (e.g. with the portal's own media component). */
  component?: PlayerComponent;
}
