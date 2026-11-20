import { createContext, useContext } from "react";
import type { ApiClient } from "./api/client";
import type { Taxonomy } from "./api/types";
import type { PlayerOptions } from "./player/types";

export interface LearningContextValue {
  api: ApiClient;
  /** Path prefix for links inside the section ("" when the section owns its own router with a basename). */
  root: string;
  player: PlayerOptions;
  /** Cached taxonomy request shared by all pages. */
  taxonomy: () => Promise<Taxonomy>;
}

export const LearningContext = createContext<LearningContextValue | null>(null);

export function useLearning(): LearningContextValue {
  const ctx = useContext(LearningContext);
  if (!ctx) throw new Error("useLearning must be used inside <LearningSection>");
  return ctx;
}

export function useLinks() {
  const { root } = useLearning();
  return {
    listing: (search = "") => `${root}/${search}`,
    detail: (id: string, start?: number) =>
      `${root}/minicodes/${encodeURIComponent(id)}${start !== undefined ? `?t=${Math.floor(start)}` : ""}`,
  };
}
