import { describe, expect, it } from "vitest";

import { isExecutableSportsEdge, rejectReasonLabel, sportsTierOf } from "@/lib/sportsEdges";

const sports = (raw: Record<string, unknown>) => ({ edge_type: "SPORTS", raw_payload: raw });

describe("sportsTierOf", () => {
  it("reads the tier the reviewer wrote into raw_payload", () => {
    expect(sportsTierOf(sports({ tier: "top_pick", candidate: true }))).toBe("top_pick");
    expect(sportsTierOf(sports({ tier: "flagged", candidate: true }))).toBe("flagged");
    expect(sportsTierOf(sports({ tier: "filtered", candidate: false }))).toBe("filtered");
  });

  it("falls back to the candidate flag when the tier is missing", () => {
    expect(sportsTierOf(sports({ candidate: false }))).toBe("filtered");
    expect(sportsTierOf(sports({ candidate: true }))).toBe("unreviewed");
    expect(sportsTierOf(sports({}))).toBe("unreviewed");
  });

  it("treats an unknown tier string as unreviewed rather than trusting it", () => {
    expect(sportsTierOf(sports({ tier: "top_pick_v2", candidate: true }))).toBe("unreviewed");
  });

  it("leaves non-sports rows alone", () => {
    expect(sportsTierOf({ edge_type: "WEATHER", raw_payload: { tier: "filtered" } })).toBeNull();
    expect(sportsTierOf({ edge_type: "MACRO", raw_payload: {} })).toBeNull();
    expect(sportsTierOf({})).toBeNull();
  });

  it("survives a null or non-object raw_payload", () => {
    expect(sportsTierOf({ edge_type: "SPORTS", raw_payload: null })).toBe("unreviewed");
    expect(sportsTierOf({ edge_type: "SPORTS", raw_payload: "oops" })).toBe("unreviewed");
  });
});

describe("isExecutableSportsEdge", () => {
  it("blocks a rejected candidate from being presented as a trade", () => {
    expect(isExecutableSportsEdge("filtered")).toBe(false);
  });

  it("allows the other tiers and non-sports rows", () => {
    expect(isExecutableSportsEdge("top_pick")).toBe(true);
    expect(isExecutableSportsEdge("flagged")).toBe(true);
    expect(isExecutableSportsEdge("unreviewed")).toBe(true);
    expect(isExecutableSportsEdge(null)).toBe(true);
  });
});

describe("rejectReasonLabel", () => {
  it("labels the reasons a filtered sports edge is shown with", () => {
    expect(rejectReasonLabel("calibration_off")).toBe("predictor miscalibrated here");
    expect(rejectReasonLabel("starts_too_soon")).toBe("starts too soon");
    expect(rejectReasonLabel("something_new")).toBe("something_new");
  });
});
