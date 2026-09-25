// Promotion-gate label for a kalshi_edges row (spec section 6).
// Only an explicit PROMOTED is trade-worthy; anything else (SHADOW, missing
// on legacy rows, unknown) is shown as Shadow: fail closed, never hidden.
export interface EdgeGateInput {
  gate_status?: string | null;
}

export interface EdgeGate {
  isShadow: boolean;
  label: "Shadow" | "Promoted";
}

export function edgeGate(edge: EdgeGateInput): EdgeGate {
  const promoted = (edge.gate_status ?? "").trim().toUpperCase() === "PROMOTED";
  return promoted ? { isShadow: false, label: "Promoted" } : { isShadow: true, label: "Shadow" };
}
