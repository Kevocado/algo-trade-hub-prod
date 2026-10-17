import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { HealthReport } from "@/lib/health";

export function useHealth() {
  const [report, setReport] = useState<HealthReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl("/api/health"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (cancelled) return;
        // `report` is null when the API has no Supabase configured. That is "no data", not "healthy",
        // so it is surfaced as an error rather than rendered as an empty healthy page.
        if (!payload?.report) throw new Error("No health report available (database not configured)");
        setReport(payload.report as HealthReport);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown health error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { report, loading, error };
}
