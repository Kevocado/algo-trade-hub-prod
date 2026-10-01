const TONES = {
  good: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  quiet: "border-slate-700 bg-slate-800/60 text-slate-300",
} as const;

export type Tone = keyof typeof TONES;

/** A one-or-two-word verdict. The word does the work; the colour only agrees with it. */
export function Chip({ tone = "quiet", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}
