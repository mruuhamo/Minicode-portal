import { useLearning } from "../context";
import { labelsFrom, type Labels } from "../format";
import { useAsync } from "./useAsync";

/** Taxonomy labels for tag ids; undefined until loaded (callers fall back to raw ids). */
export function useLabels(): Labels | undefined {
  const { taxonomy } = useLearning();
  const { data } = useAsync("taxonomy", () => taxonomy());
  return data ? labelsFrom(data) : undefined;
}
