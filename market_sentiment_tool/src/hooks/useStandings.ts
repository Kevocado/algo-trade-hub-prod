import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { Standings } from "@/lib/homeTruth";

export function useStandings() {
  const [standings, setStandings] = useState<Standings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl("/api/journal"))
      .then(async (response) => {
        // Only parse JSON when it is JSON: an HTML error page would otherwise throw an opaque
        // "Unexpected token <" and hide the status that actually explains it.
        const type = response.headers?.get?.("content-type") ?? "";
        const payload = type.includes("json") ? await response.json() : null;
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (cancelled) return;
        // No standings means an older API build. Absent is "unknown", never "nothing to report",
        // so it is surfaced as an error rather than as an empty page that looks like good news.
        if (!payload?.standings) throw new Error("This API build has no journal standings");
        setStandings(payload.standings as Standings);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown journal error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { standings, loading, error };
}