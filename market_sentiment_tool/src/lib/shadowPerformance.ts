export interface ShadowThreshold {
  yes: number;
  no: number;
}

export interface ShadowFreshness {
  asset: string;
  latest_bar: string | null;
  age_hours: number | null;
  is_stale: boolean | null;
}

export interface ShadowSummary {
  evaluated_count: number;
  considered_count: number;
  dead_zone_count: number;
  hit_rate: number | null;
  brier_score: number | null;
  virtual_pnl_pct: number;
}

export interface ShadowPerformancePoint {
  timestamp: string;
  asset: string;
  market_ticker: string;
  probability_yes: number;
  threshold_side: string | null;
  threshold_triggered: boolean;
  current_price: number;
  next_hour_price: number;
  realized_yes: number;
  shadow_outcome: "win" | "loss";
  correct: boolean;
  virtual_return_pct: number;
}

export interface ShadowPerformanceResponse {
  domain: string;
  hours: number;
  generated_at: string;
  thresholds: Record<string, ShadowThreshold>;
  summary: ShadowSummary;
  freshness: Record<string, ShadowFreshness>;
  series: ShadowPerformancePoint[];
}

export function getShadowAssets(series: ShadowPerformancePoint[]): string[] {
  return Array.from(new Set(series.map((point) => point.asset))).sort();
}


export function filterShadowSeriesByAsset(
  series: ShadowPerformancePoint[],
  asset: string,
): ShadowPerformancePoint[] {
  return series.filter((point) => point.asset === asset);
}


export function getShadowThresholdValue(
  thresholds: Record<string, ShadowThreshold>,
  asset: string,
): number | null {
  const threshold = thresholds[asset];
  return threshold ? threshold.yes : null;
}


export function getShadowMarkerColor(point: ShadowPerformancePoint): string {
  if (!point.threshold_triggered) {
    return "transparent";
  }
  return point.correct ? "#10b981" : "#f43f5e";
}


export function getShadowMarkerRadius(point: ShadowPerformancePoint): number {
  return point.threshold_triggered ? 5 : 0;
}
