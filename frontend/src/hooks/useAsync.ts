import { useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
}

/**
 * Runs `fn` whenever `key` changes and aborts the previous request.
 * Results are stored together with their key, so stale responses never show up for a newer key.
 */
export function useAsync<T>(key: string, fn: (signal: AbortSignal) => Promise<T>): AsyncState<T> {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const [state, setState] = useState<{ key: string; data?: T; error?: Error }>({ key: "" });

  useEffect(() => {
    const controller = new AbortController();
    fnRef.current(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        setState({ key, data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ key, error: error instanceof Error ? error : new Error(String(error)) });
      },
    );
    return () => controller.abort();
  }, [key]);

  const current = state.key === key;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: !current,
  };
}
