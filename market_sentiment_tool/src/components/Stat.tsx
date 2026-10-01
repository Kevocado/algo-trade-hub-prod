/** One big number and what it counts. The page's first read: a visitor should get the state from these alone. */
export function Stat({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-5 py-4">
      <div className="text-4xl font-semibold tabular-nums tracking-tight text-white">{value}</div>
      <div className="mt-1 text-sm text-slate-300">{label}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
