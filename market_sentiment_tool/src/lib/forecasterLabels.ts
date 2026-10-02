import type { Baseline } from "@/lib/journal";

/** Plain-language names for the journal's forecasters. The raw `name@version` stays in the detail view. */
const BASE: Record<string, string> = {
  cpi_nowcast: "Inflation (CPI)",
  fomc_mapped: "Fed rate decision",
  labor_nowcast: "Jobs report (payrolls)",
  unrate_direction: "Unemployment rate",
  quits_direction: "Job quits",
  sentiment_meter: "S&P 500 tomorrow: sentiment",
  spy_quant: "S&P 500 tomorrow: model",
  vix_direction: "Volatility (VIX) tomorrow",
  gold_direction: "Gold tomorrow",
  eurusd_direction: "Euro vs dollar tomorrow",
  housing_direction: "US home prices",
  sports_nfl: "NFL winners",
  sports_cfb: "College football winners",
  sports_nfl_spread: "NFL point spreads",
  sports_nfl_total: "NFL game totals",
  sports_cfb_spread: "College football point spreads",
  sports_cfb_total: "College football game totals",
};

const VERSIONED: Record<string, string> = {
  "cpi_nowcast@cpi-core-v1": "Core inflation (CPI)",
};

/** Plan 15: a market-anchored copy of a model, graded beside it. Named after the model it shadows. */
export const CAUTIOUS_SUFFIX = "_cautious";

export function forecasterLabel(forecaster: string, version?: string): string {
  if (forecaster.endsWith(CAUTIOUS_SUFFIX)) {
    const base = version?.replace(/\+w\d+$/, "");
    return `${forecasterLabel(forecaster.slice(0, -CAUTIOUS_SUFFIX.length), base)} (cautious)`;
  }
  if (version && VERSIONED[`${forecaster}@${version}`]) return VERSIONED[`${forecaster}@${version}`];
  if (BASE[forecaster]) return BASE[forecaster];
  const text = forecaster.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** What a forecaster is being compared with, in words a visitor already knows. */
export function baselineName(baseline: Baseline): string {
  if (baseline === "market") return "the Kalshi price";
  if (baseline === "climatology") return "the usual rate";
  return "no baseline yet";
}
