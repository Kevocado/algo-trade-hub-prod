import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { WeatherTodayRow, WeatherSettledRow } from "@/lib/weather";

export function useWeather() {
  const [today, setToday] = useState<WeatherTodayRow[]>([]);
  const [settled, setSettled] = useState<WeatherSettledRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl("/api/weather"))
      .then(async (response) => {
        const type = response.headers?.get?.("content-type") ?? "";
        const payload = type.includes("json") ? await response.json() : null;
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        if (cancelled) return;
        setToday(payload.today as WeatherTodayRow[]);
        setSettled(payload.settled as WeatherSettledRow[]);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown weather error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { today, settled, loading, error };
}