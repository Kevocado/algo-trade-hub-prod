import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { QuarantineResponse } from "@/lib/quarantine";

/**
 * The quarantined engines' measured output, read once.
 *
 * Kept SEPARATE from `useMarketEdges` and from `useEngineHealth`, and the three reads answer three
 * different questions that must not be able to suppress one another:
 *
 *   - `useMarketEdges().error`   "I cannot see the published rows"
 *   - `useEngineHealth().error`   "I cannot tell whether an engine ran"
 *   - `useQuarantine().error`     "I cannot see what the quarantined engines measured"
 *
 * Merging any two of them would let one hide another, and a reader shown the third as the first
 * would conclude there are no quarantined rows -- which is the same false reading as a count of zero.
 *
 * `data` stays null on failure rather than becoming a response with zero rows. That fallback would be
 * the defect this whole feature exists to fix, arrived at through a different door: an empty
 * measurement rendered as a measured empty.
 */
export function useQuarantine() {
  const [data, setData] = useState<QuarantineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetch(buildApiUrl("/api/quarantine"));
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (!cancelled) {
          setData(payload as QuarantineResponse);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          // Cleared, not left standing. A measurement from a previous successful read is a claim
          // about the current one, and rendering it beside a fresh failure would be worse than
          // either -- it would look like a live number on a surface whose whole job is not to lie.
          setData(null);
          setError(err instanceof Error ? err.message : "Unknown quarantine read error");
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
