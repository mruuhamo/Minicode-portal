// Public library entry (`@minicode/learning-section`). Import the styles once: `@minicode/learning-section/style.css`.
export { LearningSection, type LearningSectionProps } from "./LearningSection";
export { ApiError, createApiClient, toQueryString } from "./api/client";
export type { ApiClient, ApiClientOptions, TokenProvider } from "./api/client";
export type * from "./api/types";
export { createMsalTokenProvider, learningReadScope } from "./auth/msal";
export { Html5Player } from "./player/Html5Player";
export { StreamEmbedPlayer } from "./player/StreamEmbedPlayer";
export { withStartTime } from "./player/streamUrl";
export { VideoPlayer } from "./player/VideoPlayer";
export { choosePlayer, type PlayerChoice } from "./player/choosePlayer";
export type { PlayerComponent, PlayerMode, PlayerOptions, PlayerProps, Seek } from "./player/types";
