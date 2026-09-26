export type SportsTier = "top_pick" | "flagged" | "unreviewed" | "filtered";

export interface SportsReview {
  status: string;
  explainable: boolean | null;
  drivers: string[];
  red_flags: string[];
  model: string | null;
}

export interface SportsEdge {
  market_id: string;
  title: string | null;
  our_prob: number;
  market_prob: number;
  edge_pct: number;
  market_url: string;
  source_url: string;
  sport: string;
  kind: string;
  side: "yes" | "no";
  entry_price: number;
  maker: boolean;
  home: string;
  away: string;
  start_utc: string;
  game_id: string;
  tier: SportsTier;
  candidate: boolean;
  reject_reasons: string[];
  review: SportsReview | null;
  /** Promotion gate is keyed on this pair, not on the engine alone. */
  engine: string | null;
  engine_version: string | null;
  gate_status: "SHADOW" | "PROMOTED" | null;
}

export interface ScorecardSide {
  n: number;
  brier: number | null;
  pnl_per_contract: number | null;
}

export interface SportsEdgesResponse {
  as_of: string;
  edges: SportsEdge[];
  /** Upcoming rows matching the filters, counted before paging. */
  total: number;
  limit: number;
  offset: number;
  reviewer_scorecard: {
    n_settled: number;
    min_settled: number;
    approved: ScorecardSide;
    rejected: ScorecardSide;
    verdict: "insufficient" | "keep" | "drop";
  };
}

export const TIER_LABELS: Record<SportsTier, string> = {
  top_pick: "Top Picks",
  flagged: "Flagged by reviewer",
  unreviewed: "Unreviewed candidates",
  filtered: "Edges that failed the candidate filter",
};

const TIER_ORDER: SportsTier[] = ["top_pick", "flagged", "unreviewed", "filtered"];

export function groupByTier(edges: SportsEdge[]): { tier: SportsTier; edges: SportsEdge[] }[] {
  return TIER_ORDER.map((tier) => ({ tier, edges: edges.filter((e) => e.tier === tier) })).filter(
    (group) => group.edges.length > 0,
  );
}

export function formatEdgePct(edge: number): string {
  return `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)} pp`;
}

const REASONS: Record<string, string> = {
  calibration_insufficient: "predictor not yet calibrated here",
  calibration_off: "predictor miscalibrated here",
  wide_quote: "wide bid/ask",
  thin_book: "thin order book",
  low_volume: "low volume",
  starts_too_soon: "starts too soon",
  starts_too_late: "starts too far out",
};

export function rejectReasonLabel(reason: string): string {
  return REASONS[reason] ?? reason;
}

/**
 * Tier of a sports edge as seen from the generic kalshi_edges row that Prediction Lab reads
 * directly from Supabase. The reviewer writes the tier into raw_payload, so a sports edge that
 * FAILED the candidate filter (predictor miscalibrated in this price bucket, wide quote, starts
 * too soon) would otherwise render in the Lab exactly like a Top Pick, behind an
 * "Execute Trade" button. Non-sports rows have no tier and must not be affected.
 */
export function sportsTierOf(edge: { edge_type?: string | null; raw_payload?: unknown }): SportsTier | null {
  if ((edge.edge_type ?? "").toUpperCase() !== "SPORTS") return null;
  const raw = (edge.raw_payload ?? {}) as { tier?: unknown; candidate?: unknown };
  if (typeof raw.tier === "string" && raw.tier in TIER_LABELS) return raw.tier as SportsTier;
  // No tier recorded: fall back to the candidate flag, then to unreviewed (fail visible).
  if (raw.candidate === false) return "filtered";
  return "unreviewed";
}

/** A rejected candidate is not tradeable and must not be presented as an executable trade. */
export function isExecutableSportsEdge(tier: SportsTier | null): boolean {
  return tier !== "filtered";
}
