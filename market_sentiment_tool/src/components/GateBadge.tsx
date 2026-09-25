import { Badge } from "@/components/ui/badge";
import { edgeGate, type EdgeGateInput } from "@/lib/edgeGate";

export function GateBadge({ edge }: { edge: EdgeGateInput }) {
  const gate = edgeGate(edge);
  return (
    <Badge
      variant="outline"
      title={
        gate.isShadow
          ? "Shadow: this engine has not passed the promotion gate yet. Tracked, not trade-worthy."
          : "Promoted: this engine passed the promotion gate."
      }
      className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
        gate.isShadow
          ? "bg-slate-500/10 text-slate-400 border-slate-500/40 border-dashed"
          : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
      }`}
    >
      {gate.label}
    </Badge>
  );
}
