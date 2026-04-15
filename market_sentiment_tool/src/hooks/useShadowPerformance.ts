import { useEffect, useMemo, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { ShadowPerformanceResponse } from "@/lib/shadowPerformance";

type UseShadowPerformanceOptions = {
  domain: string;
  hours: number;
  pollMs?: number;
};

export function useShadowPerformance({
  domain,
  hours,
  pollMs = 60_000,
}: UseShadowPerformanceOptions) {
  const [data, setData] = useState<ShadowPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const url = useMemo(() => {
    const params = new URLSearchParams({ domain, hours: String(hours) });
    return buildApiUrl(`/api/shadow-performance?${params.toString()}`);
  }, [domain, hours]);

  useEffect(() => {
    let cancelled = false;

    const load = async (isBackgroundRefresh: boolean) => {
      if (isBackgroundRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      try {
        const response = await fetch(url);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (!cancelled) {
          setData(payload as ShadowPerformanceResponse);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown shadow dashboard error");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };

    void load(false);
    const intervalId = window.setInterval(() => {
      void load(true);
    }, pollMs);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [pollMs, reloadKey, url]);

  return {
    data,
    loading,
    refreshing,
    error,
    reload: () => setReloadKey((value) => value + 1),
  };
}
