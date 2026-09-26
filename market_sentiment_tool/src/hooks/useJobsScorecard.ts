import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { JobsScorecardRow, JobsSeries } from "@/lib/jobsScorecard";

export function useJobsScorecard(series: JobsSeries) {
  const [rows, setRows] = useState<JobsScorecardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl(`/api/jobs-scorecard?series=${series}`))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (!cancelled) {
          setRows(payload as JobsScorecardRow[]);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown scorecard error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [series]);

  return { rows, loading, error };
}
