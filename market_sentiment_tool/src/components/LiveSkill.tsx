import { forecasterLabel } from "@/lib/forecasterLabels";
import type { JournalScore } from "@/lib/journal";

const Z95 = 1.96;
const TOO_EARLY_N = 30;
const AHEAD = "#10b981";
const BEHIND = "#f87171";
const NEUTRAL = "#94a3b8";

interface Row {
  key: string;
  label: string;
  gap: number;
  se: number | null;
  n: number;
}

/** Live forecasters graded against the Kalshi price. The Kalshi mid and the naive baselines are what the
 *  others are measured against, so they are not rows. A forecaster with no measured gap is not drawn. */
export function liveRows(scores: JournalScore[]): Row[] {
  return scores
    .filter((s) => s.baseline === "market" && s.gap != null && s.n_settled > 0)
    .filter((s) => !s.forecaster.startsWith("kalshi_implied_") && !s.forecaster.startsWith("baseline_"))
    .map((s) => ({
      key: `${s.forecaster}@${s.forecaster_version}`,
      label: forecasterLabel(s.forecaster, s.forecaster_version),
      gap: s.gap as number,
      se: s.gap_se ?? null,
      n: s.n_settled,
    }))
    .sort((a, b) => a.gap - b.gap);
}

/** "-0.002 ± 0.008": three decimals, a dash when a figure was not measured. */
export function gapText(gap: number, se: number | null): string {
  const g = `${gap < 0 ? "−" : gap > 0 ? "+" : ""}${Math.abs(gap).toFixed(3)}`;
  return se === null ? g : `${g} ± ${(Z95 * se).toFixed(3)}`;
}

/** ahead / behind only when the whole 95% interval is on one side of zero; otherwise "No signal". */
export function verdict(gap: number, se: number | null): "ahead" | "behind" | "none" {
  if (se === null) return "none";
  if (gap + Z95 * se < 0) return "ahead";
  if (gap - Z95 * se > 0) return "behind";
  return "none";
}

const COLOR = { ahead: AHEAD, behind: BEHIND, none: NEUTRAL };
const WORD = { ahead: "Ahead", behind: "Behind", none: "No signal" };

/** One row per forecaster: its Brier gap against the Kalshi price as a dot, the 95% interval as a bar,
 *  a labelled zero line. Plain HTML so labels never collide and it reads at phone width.
 *  Nothing is computed here: gap and standard error come from the scorecard. */
export function LiveSkill({ scores }: { scores: JournalScore[] }) {
  const rows = liveRows(scores);
  if (rows.length === 0) return <p className="text-sm text-slate-500">No forecaster has a measured gap yet.</p>;

  const reach = Math.max(...rows.map((r) => Math.abs(r.gap) + (r.se === null ? 0 : Z95 * r.se)), 0.01);
  const span = Math.ceil(reach * 100) / 100;           // symmetric, rounded outward to 0.01
  const pos = (v: number) => `${((v + span) / (2 * span)) * 100}%`;

  return (
    <div role="list" aria-label="Skill against the Kalshi price" className="space-y-2">
      <div className="grid grid-cols-[minmax(0,9rem)_1fr_7.5rem] items-end gap-3 text-[10px] text-slate-500 sm:grid-cols-[14rem_1fr_9rem]">
        <span />
        <div className="relative h-4">
          <span className="absolute left-0">{(-span).toFixed(2)} better</span>
          <span className="absolute -translate-x-1/2" style={{ left: "50%" }}>0</span>
          <span className="absolute right-0">worse {span.toFixed(2)}</span>
        </div>
        <span />
      </div>
      {rows.map((r) => {
        const v = verdict(r.gap, r.se);
        const half = r.se === null ? 0 : Z95 * r.se;
        return (
          <div role="listitem" key={r.key}
            className="grid grid-cols-[minmax(0,9rem)_1fr_7.5rem] items-center gap-3 text-xs sm:grid-cols-[14rem_1fr_9rem]">
            <span className="truncate text-slate-200" title={r.label}>{r.label}</span>
            <div className="relative h-5">
              <div className="absolute inset-y-0 w-px bg-slate-500" style={{ left: "50%" }} />
              {half > 0 && (
                <div className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded"
                  style={{ left: pos(r.gap - half), width: `${(2 * half / (2 * span)) * 100}%`, background: COLOR[v], opacity: 0.55 }} />
              )}
              <div data-testid="dot" data-hollow={r.n < TOO_EARLY_N}
                className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{ left: pos(r.gap), background: r.n < TOO_EARLY_N ? "transparent" : COLOR[v], border: `2px solid ${COLOR[v]}` }} />
            </div>
            <span className="text-right tabular-nums text-slate-300">
              {gapText(r.gap, r.se)}
              <span className="block text-[10px] text-slate-500">{WORD[v]} · {r.n} scored</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
