import { settledBars, type ScoreboardRow, type SettledBar } from "@/lib/scoreboard";

/**
 * One bar. Its own heading, so the two can never be read as one number.
 *
 * Extracted from `src/pages/Scoreboard.tsx` rather than copied for a second page, for the same
 * reason `settledBars()` lives in `@/lib/scoreboard` and not in either page: a second drawing of
 * the two bars is a second thing to keep wrong, and the failure it invites is the exact one this
 * product refuses -- a monthly engine holding 70 settled rendered as 70/100, unmet, which is a
 * verdict against a bar that was never its own.
 */
function Bar({ bar }: { bar: SettledBar }) {
  // Tri-state, and null is rendered as its own thing: collapsing "not measured" into "not met"
  // turns a gap in the evidence into a verdict against the engine.
  const verdict =
    bar.met === null
      ? { text: "Not measured", className: "bg-slate-700/40 text-slate-400 border-slate-600" }
      : bar.met
        ? { text: "Met", className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30" }
        : { text: "Not met", className: "bg-amber-500/10 text-amber-300 border-amber-500/30" };

  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
          {bar.label}
        </span>
        <span
          className={`rounded-full border px-1.5 py-px text-[9px] font-bold uppercase ${verdict.className}`}
        >
          {verdict.text}
        </span>
      </div>
      {/* The fill is the response's own capped percentage. No bar is drawn where none was measured. */}
      {bar.pct !== null && (
        <div className="mt-1 h-1 w-28 rounded-full bg-slate-800">
          <div
            className={`h-1 rounded-full ${bar.met ? "bg-emerald-500" : "bg-amber-500"}`}
            style={{ width: `${bar.pct}%` }}
          />
        </div>
      )}
      <div className="text-[11px] leading-tight text-slate-400">{bar.line}</div>
    </div>
  );
}

/**
 * Both bars, for one scoreboard row. A fragment, deliberately: the scoreboard's own tests count
 * the "Met" / "Not measured" labels inside a row, and a wrapper element here would be a silent
 * change to an approved page for no gain.
 */
export function SettledBars({ row }: { row: ScoreboardRow }) {
  return <>{settledBars(row).map((bar) => <Bar key={bar.key} bar={bar} />)}</>;
}
