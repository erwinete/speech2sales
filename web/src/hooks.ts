/** Хук URL-параметров поверх History API (без react-router-dom). */

import { useCallback, useEffect, useState } from "react";

export function useSearchParams(): [URLSearchParams, (update: Record<string, string | null>) => void] {
  const [params, setParams] = useState(() => new URLSearchParams(window.location.search));

  useEffect(() => {
    const sync = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const update = useCallback((changes: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    window.history.pushState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    setParams(new URLSearchParams(qs));
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  return [params, update];
}
