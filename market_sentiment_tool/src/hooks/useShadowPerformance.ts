import { useEffect, useMemo, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { ShadowPerformanceResponse } from "@/lib/shadowPerformance";

type UseShadowPerformanceOptions = {
  domain: string;
  hours: number;
  pollMs?: number;
};

/**
 * A failed read, with enough of the response to word it honestly.
 *
 * The message alone is not enough and this hook used to throw it away. The
 * difference between "the database is not renamed yet, apply this file" and
 * "the network is down" is in the body the server sent, and the caller cannot
 * classify a bare string without guessing at its wording. So the status and the
 * detail are kept as the server sent them, and `shadowUnavailable` in
 * `@/lib/shadowPerformance` does the wording.
 */
export interface ShadowReadError {
  /** `detail` from the response body, or a synthesised status line. */
  message: string;
  status: number | null;
}

/**
 * A failed read, carrying the status it failed with.
 *
 * A bare `Error` was the old shape and it threw away the one field that
 * separates "the database has not been renamed yet, apply this file" from "the
 * network is down": the response status. Recovering it by pattern-matching the
 * message was worse, because the interesting message is the one that does not
 * look like a status line. So the status is attached where the response is
 * still in scope, and a transport failure -- `fetch` rejecting, no response at
 * all -- carries `null` rather than an invented one.
 */
class ShadowRequestError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ShadowRequestError";
    this.status = status;
  }
}

export function useShadowPerformance({
  domain,
  hours,
  pollMs = 60_000,
}: UseShadowPerformanceOptions) {
  const [data, setData] = useState<ShadowPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<ShadowReadError | null>(null);
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
          throw new ShadowRequestError(
            payload?.detail || `Request failed with status ${response.status}`,
            response.status,
          );
        }
        if (!cancelled) {
          setData(payload as ShadowPerformanceResponse);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          const failure =
            err instanceof ShadowRequestError
              ? err
              : new ShadowRequestError(
                  err instanceof Error ? err.message : "Unknown shadow dashboard error",
                  null,
                );
          setError({ message: failure.message, status: failure.status });
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
