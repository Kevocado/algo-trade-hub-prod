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
        // Only parse JSON when it is JSON: an HTML error page (the SPA catch-all, a proxy 502) would
        // otherwise throw an opaque "Unexpected token <" and hide the status that actually explains it.
        const type = response.headers?.get?.("content-type") ?? "";
        const isJson = type.includes("json");
        const payload = isJson ? await response.json() : null;
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (cancelled) return;
        // `report` is null only on an older API build that predates the report. Absent credentials are
        // NOT this case -- the report is populated and reads `never`/`missing`. Either way an absent
        // report is "unknown", never "healthy", so it is surfaced as an error.
        if (!payload?.report) throw new Error("This API build has no health report");
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
