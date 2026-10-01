import { describe, expect, it } from "vitest";

import {
  RANKING_SENTENCE,
  formatEdgePct,
  groupByTier,
  rankingSentence,
  rejectReasonLabel,
  type SportsEdge,
  type SportsEdgesResponse,
  type SportsRanking,
} from "@/lib/sportsEdges";

const base: SportsEdge = {
  market_id: "KXNFLGAME-26SEP27HOUIND-IND", title: "IND wins", our_prob: 0.3, market_prob: 0.25, edge_pct: 0.075,
  market_url: "https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26sep27houind",
  source_url: "https://sports.example.com/?sport=nfl&game=2026_03_HOU_IND", sport: "nfl", kind: "winner",
  side: "yes", entry_price: 0.25, maker: true, home: "IND", away: "HOU", start_utc: "2026-09-27T17:00:00+00:00",
  game_id: "2026_03_HOU_IND", tier: "top_pick", candidate: true, reject_reasons: [], review: null,
  engine: "sports_nfl", engine_version: "feed:ridge@2026-09-04T22:12:49.750941+00:00", gate_status: "SHADOW",
};

describe("sports edges", () => {
  it("groups edges into the four tiers in display order", () => {
    const groups = groupByTier([
      { ...base, market_id: "f", tier: "filtered" },
      { ...base, market_id: "t", tier: "top_pick" },
      { ...base, market_id: "u", tier: "unreviewed" },
      { ...base, market_id: "x", tier: "flagged" },
    ]);
    expect(groups.map((g) => g.tier)).toEqual(["top_pick", "flagged", "unreviewed", "filtered"]);
    expect(groups[0].edges.map((e) => e.market_id)).toEqual(["t"]);
  });

  it("drops empty tiers", () => {
    expect(groupByTier([base]).map((g) => g.tier)).toEqual(["top_pick"]);
  });

  it("formats edges as percentage points", () => {
    expect(formatEdgePct(0.075)).toBe("+7.5 pp");
  });

  it("labels reject reasons in plain words", () => {
    expect(rejectReasonLabel("calibration_insufficient")).toBe("predictor not yet calibrated here");
    expect(rejectReasonLabel("something_new")).toBe("something_new");
  });
});

/**
 * Which ranking the table is ordered by, in the one sentence that says so.
 *
 * This sentence is the entire claim the feature makes to a reader. Getting it backwards is not a
 * cosmetic bug -- the board is still sorted the same way, so nothing else on the page disagrees with
 * it, and the whole Python suite stays green through it. So the three states the backend can report
 * are each spelled out here, and the two properties that matter are pinned as properties rather than
 * as the current wording.
 */

/** The part of the sentence that makes the claim. Everything after the first `:` is a qualifier. */
function claim(sentence: string): string {
  return sentence.replace(/^Ranked by /, "").split(":")[0];
}

/**
 * A response carrying the mode the backend reported.
 *
 * The served row has no `sigma` field -- it stays out of `edge_row`'s payload on purpose -- so a
 * fully scored board and a partly scored one are byte-identical to this file. That is the reason the
 * helper takes the mode and nothing else, and the reason the two states share a literal: the page
 * cannot tell them apart, so the sentence it shows has to be true for both.
 *
 * `edges` takes no argument any more. It used to, for a test that built two DIFFERENT edge lists and
 * asserted they produced the same sentence -- which passed only because both lists were in fact
 * identical, and because `ranking` is an input here rather than something derived from the list.
 * There is no honest way to derive `ranking` from a payload in this file, so the parameter went with
 * the test. See the note where it used to be.
 */
function payload(ranking: SportsRanking): SportsEdgesResponse {
  return {
    as_of: "2026-09-27T12:00:00+00:00",
    edges: [base],
    total: 1,
    candidate_count: 1,
    limit: 50,
    offset: 0,
    ranking,
    reviewer_scorecard: {
      n_settled: 0,
      min_settled: 100,
      approved: { n: 0, brier: null, pnl_per_contract: null },
      rejected: { n: 0, brier: null, pnl_per_contract: null },
      verdict: "insufficient",
    },
  };
}

describe("which ranking the page claims", () => {
  it("does not claim confidence ranking when the payload says raw_edge", () => {
    // Today's state: sigma is null on every game the feed publishes, so the sort fell back to raw
    // edge. The sentence is the ONLY thing that admits it, and the qualifier after the colon may
    // mention sigma precisely because it denies having one.
    const sentence = rankingSentence(payload("raw_edge").ranking);

    expect(claim(sentence)).toMatch(/raw edge/i);
    expect(claim(sentence)).not.toMatch(/sigma/i);
  });

  it("claims confidence ranking when the payload says edge_sigma", () => {
    const sentence = rankingSentence(payload("edge_sigma").ranking);

    expect(claim(sentence)).toMatch(/sigma/i);
    expect(claim(sentence)).not.toMatch(/^raw edge/i);
  });

  it("keeps the edge_sigma sentence true when only some rows are scored", () => {
    // The score is per row, so a partly-publishing feed sorts a mix of z-scored keys and raw-decimal
    // keys in one comparison. The sentence has to name the fallback for the unscored rows, or it
    // tells a reader that everything above them was ranked on confidence when it was not.
    const sentence = rankingSentence(payload("edge_sigma").ranking);

    expect(sentence).toMatch(/raw edge/i);
    expect(sentence).not.toMatch(/\ball\b|\bevery\b|\bonly\b/i);
  });

  it("says the sentence that claims least when the field is absent", () => {
    // A backend predating the field sends no `ranking` at all. The branch on `=== "edge_sigma"`
    // degrades to the raw-edge sentence, which is the conservative direction; now it is designed
    // rather than accidental, and this is what holds it in place.
    expect(rankingSentence(undefined)).toBe(RANKING_SENTENCE.raw_edge);
    expect(rankingSentence(null)).toBe(RANKING_SENTENCE.raw_edge);
  });

  // A test that used to sit here claimed to give "a fully scored board and a partly scored one the
  // same sentence", and could not have failed: the two fixtures were byte-identical, and `ranking`
  // is an INPUT to `rankingSentence` rather than something derived from the edges. It asserted its
  // own argument round-tripped, so deleting the sentence's `raw edge` qualifier would have left it
  // green. There is no replacement here because the two boards are genuinely indistinguishable in
  // this file -- see the `payload` docstring -- and the property is now stated where it is
  // testable: the `edge_sigma` sentence must NAME the fallback ("keeps the edge_sigma sentence true
  // when only some rows are scored" above), which fails the moment it claims a total order.
});
