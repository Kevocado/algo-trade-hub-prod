import { useEffect, useState } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, ReferenceLine, XAxis, YAxis } from "recharts";
import { getJson } from "@/lib/getJson";

const CORRECT = "#10b981";   // green: our prediction matched the outcome
const WRONG = "#f87171";     // red: our prediction was wrong

interface WeatherContract {
  target: string;
  forecaster: string;
  our_prob: number | null;
  market_prob: number | null;
  outcome: number | null;
}

interface WeatherPanelResponse {
  as_of: string;
  settled_date: string | null;
  contracts: WeatherContract[];
}

export type { WeatherPanelResponse };

/** Weather/ERCOT panel: per-contract probability vs Kalshi's on a 45-degree scatter,
    points coloured by outcome (green = our call was right, red = wrong).
    Missing figures render as a dash, never 0%. Data from /api/journal/weather-panel. */
export function WeatherPanel() {
  const [data, setData] = useState<WeatherPanelResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<WeatherPanelResponse>("/api/journal/weather-panel")
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="p-4 rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
        <p className="font-semibold">Weather panel unavailable</p>
        <p className="mt-1 text-rose-300/80">{error}</p>
      </div>
    );
  }

  const contracts = data?.contracts?.filter(
    (c) => c.our_prob !== null && c.market_prob !== null && c.outcome !== null,
  ) ?? [];

  const settledDate = data?.settled_date ?? null;

  return (
    <section aria-label="Weather vs ERCOT vs Kalshi" className="space-y-4">
      <header className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Weather & ERCOT</h2>
        {settledDate && (
          <span className="text-[10px] text-slate-500">Latest settled: {settledDate}</span>
        )}
      </header>

      {contracts.length === 0 && (
        <p className="text-xs text-slate-500">No settled weather/ERCOT contracts yet.</p>
      )}

      {contracts.length > 0 && (
        <ResponsiveContainer width="100%" height={260}>
          <ScatterChart data={contracts} margin={{ top: 20, right: 40, bottom: 40, left: 50 }}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis
              type="number"
              dataKey="our_prob"
              domain={[0, 1]}
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              type="number"
              dataKey="market_prob"
              domain={[0, 1]}
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            {/* 45-degree reference line: our probability = Kalshi's probability */}
            <ReferenceLine x={0} y={0} x2={1} y2={1} stroke="#64748b" strokeWidth={1} strokeDasharray="3 3" />
            {/* Points coloured by outcome */}
            <Scatter
              name="Outcome matched our call"
              data={contracts.filter((c) => c.outcome !== null && ((c.our_prob! > 0.5) === (c.outcome === 1)))}
              dataKey="our_prob"
              fill={CORRECT}
            />
            <Scatter
              name="Our call missed"
              data={contracts.filter((c) => c.outcome !== null && ((c.our_prob! > 0.5) !== (c.outcome === 1)))}
              dataKey="our_prob"
              fill={WRONG}
            />
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}