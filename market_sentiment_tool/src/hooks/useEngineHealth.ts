import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { EngineHealthResponse } from "@/lib/engineHealth";

/**
 * The written ruling on which engines could not run, read once.
 *
 * A failure is STATE, not a `console.error`, and it is kept separate from the edge board's own
 * `useMarketEdges().error`. The two are different gaps and merging them would let one suppress the
 * other: a board that could not be read is "I cannot see the rows", and a ruling that could not be
 * read is "I cannot tell whether the engine ran". A reader shown the first as the second has been
 * told the product's central question is unanswerable when in fact it was a 500.
 *
 * `data` stays null on failure rather than becoming a response with every state "ran". That
 * fallback would be the defect this whole feature exists to fix: an empty board rendered as a
 * measured zero because the read failed. So there is no default, and `error` has to be checked.
 */
export function useEngineHealth() {
  const [data, setData] = useState<EngineHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetch(buildApiUrl("/api/engine-health"));
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (!cancelled) {
          setData(payload as EngineHealthResponse);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          // Cleared, not left standing. A ruling from a previous successful read is a claim about
          // the current one, and rendering it beside a fresh failure would be worse than either.
          setData(null);
          setError(err instanceof Error ? err.message : "Unknown engine-health error");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { data, loading, error };
}
