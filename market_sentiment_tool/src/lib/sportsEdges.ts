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
  /** The quote MID. Not what `edge_pct` is compared against -- see `rank_edge_pct`. */
  market_prob: number;
  /**
   * The after-fee edge against the ENTRY price on `side`, or null when the candidate filter
   * rejected the row. A wide quote makes this number large without the model disagreeing with the
   * market by much at all, which is why it is withheld rather than shown small.
   */
  edge_pct: number | null;
  /** The same number, for ranking across page boundaries. Never render it as a headline. */
  rank_edge_pct?: number | null;
  /** yes_ask - yes_bid on the entry side. The thing that explains the number above. */
  quote_spread?: number | null;
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
  /** Null when the scan only had the `feed:unknown` placeholder; see `model_version_known`. */
  engine_version: string | null;
  model_version_known?: boolean;
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
  /**
   * How many of the WHOLE filtered set passed the candidate filter, counted before paging.
   *
   * A page cannot supply this: rows are ranked candidates-first, so page 2+ is always the reject
   * tail, and a page-derived count reports "all rejected" on a board whose page 1 is full of picks.
   */
  candidate_count: number;
  limit: number;
  offset: number;
  /**
   * Which ranking the response used: `edge_sigma` when the feed supplied a real sigma, else
   * `raw_edge`. `sigma` is null on every game as of 2026-09-27, so this is `raw_edge` in practice --
   * and the page says which, because claiming to rank by confidence while ranking by raw edge is
   * worse than never claiming it.
   */
  ranking: "edge_sigma" | "raw_edge";
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

export function formatEdgePct(edge: number | null | undefined): string {
  if (edge === null || edge === undefined) return "\u2014";
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
