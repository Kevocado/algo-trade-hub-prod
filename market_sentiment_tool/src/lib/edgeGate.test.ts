import { describe, expect, it } from "vitest";

import { edgeGate } from "@/lib/edgeGate";

describe("edgeGate", () => {
  it("labels only PROMOTED edges as promoted", () => {
    expect(edgeGate({ gate_status: "PROMOTED" })).toEqual({ isShadow: false, label: "Promoted" });
  });

  it("labels SHADOW edges as shadow", () => {
    expect(edgeGate({ gate_status: "SHADOW" })).toEqual({ isShadow: true, label: "Shadow" });
  });

  it("fails closed: missing, null or unknown statuses are shadow", () => {
    expect(edgeGate({}).isShadow).toBe(true);
    expect(edgeGate({ gate_status: null }).isShadow).toBe(true);
    expect(edgeGate({ gate_status: "promoted " }).isShadow).toBe(false);
    expect(edgeGate({ gate_status: "DEMOTED" }).isShadow).toBe(true);
  });
});
