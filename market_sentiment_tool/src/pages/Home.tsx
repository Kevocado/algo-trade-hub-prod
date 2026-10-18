import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";

import { useStandings } from "@/hooks/useStandings";
import {
  HOME_INTRO,
  gapText,
  headlineStats,
  homeLinks,
  plainName,
  verdictChip,
  type Chip,
  type StandingEntry,
} from "@/lib/homeTruth";

const toneClass: Record<Chip["tone"], string> = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  flat: "border-slate-600/60 bg-slate-700/20 text-slate-400",
};

function ChipBadge({ chip }: { chip: Chip }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass[chip.tone]}`}
    >
      {chip.label}
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-black tracking-tight text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}

function EndRow({ entry, label }: { entry: StandingEntry; label: string }) {
  const sessions = entry.n;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
          <div className="truncate text-sm font-semibold text-slate-200">
            {plainName(entry.forecaster)}
            <span className="ml-2 font-mono text-[11px] text-slate-500">{entry.forecaster}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* A dash when either half is missing: there is no bar for the gap to clear. */}
          <span className="text-sm tabular-nums text-slate-200">{gapText(entry.gap, entry.se)}</span>
          <ChipBadge chip={verdictChip(entry.verdict)} />
        </div>
      </div>
      <p className="mt-1.5 text-xs text-slate-500">
        {sessions === null ? "replayed over an unrecorded number of sessions" : `over ${sessions} replayed sessions`}
        {entry.date_to ? ` · ${entry.date_from} to ${entry.date_to}` : ""}
        {entry.n_settled === null ? "" : ` · ${entry.n_settled} settled`}
      </p>
    </div>
  );
}

function LeaderboardSection({
  title,
  best,
  worst,
  forecasters,
}: {
  title: string;
  best: StandingEntry | null;
  worst: StandingEntry | null;
  forecasters: string[];
}) {
  if (!best) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">{title}</h2>
      <EndRow entry={best} label="Best" />
      {worst ? <EndRow entry={worst} label="Worst" /> : null}
      <p className="text-xs text-slate-500">
        {forecasters.length} forecasters · A gap counts as a result only when it clears 2 standard errors.
        Anything inside that bar is noise, whatever its sign.
      </p>
    </section>
  );
}

export default function Home() {
  const { standings, loading, error } = useStandings();
  const s = standings ? headlineStats(standings) : null;

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-8">
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        <header className="border-b border-slate-900 pb-6">
          <div className="text-xs font-bold uppercase tracking-widest text-emerald-400">Findings</div>
          <h1 className="mt-2 text-3xl font-black uppercase italic tracking-tight text-white sm:text-4xl">
            What we found
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">{HOME_INTRO}</p>
        </header>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : standings && s ? (
          <>
            {/* The lede, assembled on the server from the numbers below. */}
            <p className="text-base leading-relaxed text-slate-200">{standings.verdict}</p>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Settled" value={s.settled} sub="frozen and scored" />
              <Stat label="Forecasters" value={s.forecasters} sub={`${s.replayed} replayed`} />
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <div className="text-[11px] uppercase tracking-wider text-slate-500">Best (vs Kalshi)</div>
                <div className="mt-1 truncate text-sm font-bold text-white">{s.bestName}</div>
                <div className="text-xs tabular-nums text-slate-400">{s.bestGap}</div>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <div className="text-[11px] uppercase tracking-wider text-slate-500">Worst (vs Kalshi)</div>
                <div className="mt-1 truncate text-sm font-bold text-white">{s.worstName}</div>
                <div className="text-xs tabular-nums text-slate-400">{s.worstGap}</div>
              </div>
            </div>

            {/* Market-linked section: graded against the Kalshi price */}
            <LeaderboardSection
              title="Graded vs Kalshi price"
              best={standings.market_linked_best}
              worst={standings.market_linked_worst}
              forecasters={standings.market_linked}
            />

            {/* Climatology section: graded against the usual rate */}
            <LeaderboardSection
              title="Graded vs climatology"
              best={standings.climatology_best}
              worst={standings.climatology_worst}
              forecasters={standings.climatology}
            />

            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">Go deeper</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {homeLinks.map((link) => (
                  <Link
                    key={link.to}
                    to={link.to}
                    className="group flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 transition-colors hover:border-slate-700 hover:bg-slate-900"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-slate-200">{link.label}</div>
                      <div className="truncate text-xs text-slate-500">{link.blurb}</div>
                    </div>
                    <ArrowRight
                      className="h-4 w-4 shrink-0 text-slate-600 transition-colors group-hover:text-slate-300"
                      aria-hidden="true"
                    />
                  </Link>
                ))}
              </div>
            </section>

            <p className="pb-6 text-xs text-slate-600">
              This product places no orders. Every number is a measurement of a forecast, not a return.
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}