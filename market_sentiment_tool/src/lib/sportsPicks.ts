import type { SportsEdge, SportsTier } from "@/lib/sportsEdges";

/**
 * The sports page's view of the edge rows: one pick per game, in plain terms.
 * Presentation only. The server decided which rows pass the candidate filter and which tier each is in;
 * this only folds duplicate rows together and states the comparison in words a fan would use.
 */

/**
 * A model/market gap bigger than this is shown, but never as a top pick or a headline.
 * Chosen before looking at outcomes: when a model says 78% and the market says 32%, someone is wrong, and
 * with no settled record yet the likelier culprit is the model. Revisit with data, not by feel.
 */
export const LARGE_GAP_POINTS = 25;

export interface SportsPick {
  key: string;
  gameId: string;
  sport: string;
  kind: string;
  matchup: string;
  startUtc: string;
  /** "UConn to win", or the market title for spreads and totals. */
  call: string;
  /** Model and market probability that THIS pick wins, 0-100. */
  model: number;
  market: number;
  /** Model minus market for this pick, in points. */
  gap: number;
  largeGap: boolean;
  tier: SportsTier;
  entryCents: number;
  marketUrl: string;
  sourceUrl: string;
}

const letters = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z]/g, "");

/** "Iowa St." names the same team as "Iowa State": compare by letters, either one a prefix of the other. */
function sameTeam(a: string, b: string): boolean {
  const x = letters(a);
  const y = letters(b);
  return x.length > 0 && y.length > 0 && (x.startsWith(y) || y.startsWith(x));
}

function callOf(edge: SportsEdge): string {
  if (edge.kind === "winner") {
    const named = (edge.title ?? "").replace(/\s+wins\s*$/i, "").trim();
    const other = sameTeam(named, edge.home) ? edge.away : sameTeam(named, edge.away) ? edge.home : null;
    if (edge.side === "yes") return `${named || edge.title} to win`;
    return other ? `${other} to win` : `${named} to lose`;
  }
  return `${edge.title ?? edge.market_id} (${edge.side.toUpperCase()})`;
}

/** The pick's gap in points: for a NO side the model's edge is the market's overpricing of YES. */
export function gapPoints(edge: Pick<SportsEdge, "our_prob" | "market_prob" | "side">): number {
  const diff = edge.our_prob - edge.market_prob;
  return (edge.side === "yes" ? diff : -diff) * 100;
}

function toPick(edge: SportsEdge): SportsPick {
  const yes = edge.side === "yes";
  const gap = gapPoints(edge);
  return {
    key: edge.market_id,
    gameId: edge.game_id,
    sport: edge.sport,
    kind: edge.kind,
    matchup: `${edge.away} @ ${edge.home}`,
    startUtc: edge.start_utc,
    call: callOf(edge),
    model: Math.round((yes ? edge.our_prob : 1 - edge.our_prob) * 100),
    market: Math.round((yes ? edge.market_prob : 1 - edge.market_prob) * 100),
    gap,
    largeGap: gap > LARGE_GAP_POINTS,
    tier: edge.tier,
    entryCents: Math.round(edge.entry_price * 100),
    marketUrl: edge.market_url,
    sourceUrl: edge.source_url,
  };
}

/**
 * One row per game and bet type. A winner market exists for BOTH teams, so "UConn wins YES" and
 * "Syracuse wins NO" are the same bet; keeping both is what made the board look twice as long and
 * twice as sure. The row with the larger gap is kept (ties: the first seen).
 */
export function toPicks(edges: SportsEdge[]): SportsPick[] {
  const best = new Map<string, SportsPick>();
  for (const edge of edges) {
    const pick = toPick(edge);
    const key = `${edge.game_id}|${edge.kind}`;
    const held = best.get(key);
    if (!held || pick.gap > held.gap) best.set(key, pick);
  }
  return [...best.values()].sort((a, b) => b.gap - a.gap);
}

export interface Board {
  topPicks: SportsPick[];
  flagged: SportsPick[];
  unreviewed: SportsPick[];
  /** Games whose only rows failed the server's candidate filter: counted, not listed. */
  noEdge: number;
}

export function board(edges: SportsEdge[]): Board {
  const all = toPicks(edges);
  const shown = all.filter((p) => p.tier !== "filtered");
  return {
    // A top pick must also be a plausible one: a large gap is a reason to doubt, not to feature.
    topPicks: shown.filter((p) => p.tier === "top_pick" && !p.largeGap),
    flagged: shown.filter((p) => p.tier === "flagged" || (p.tier === "top_pick" && p.largeGap)),
    unreviewed: shown.filter((p) => p.tier === "unreviewed"),
    noEdge: all.length - shown.length,
  };
}

export function gapText(gap: number): string {
  return `${gap > 0 ? "+" : ""}${Math.round(gap)}`;
}
