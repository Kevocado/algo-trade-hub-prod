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
}

export interface ScorecardSide {
  n: number;
  brier: number | null;
  pnl_per_contract: number | null;
}

export interface SportsEdgesResponse {
  as_of: string;
  edges: SportsEdge[];
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
