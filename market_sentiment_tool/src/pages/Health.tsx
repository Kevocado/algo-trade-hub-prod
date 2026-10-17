import { Activity, AlertTriangle, Loader2 } from "lucide-react";

import { useHealth } from "@/hooks/useHealth";
import {
  HEALTH_INTRO,
  familyRows,
  formatAge,
  healthSummary,
  statusChip,
  timerRows,
  type Chip as ChipTone,
} from "@/lib/health";

const toneClass: Record<ChipTone["tone"], string> = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

function ChipBadge({ chip }: { chip: ChipTone }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass[chip.tone]}`}>
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

export default function Health() {
  const { report, loading, error } = useHealth();

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="border-b border-slate-900 pb-6">
          <div className="flex items-center gap-2 text-emerald-400">
            <Activity className="h-5 w-5" aria-hidden="true" />
            <span className="text-xs font-bold uppercase tracking-widest">System</span>
          </div>
          <h1 className="mt-2 text-3xl font-black uppercase italic tracking-tight text-white sm:text-4xl">
            Health
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">{HEALTH_INTRO}</p>
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
        ) : report ? (
          <HealthBody report={report} />
        ) : null}
      </div>
    </div>
  );
}

function HealthBody({ report }: { report: import("@/lib/health").HealthReport }) {
  const s = healthSummary(report);
  const timers = timerRows(report);
  const families = familyRows(report);
  const ob = report.orderbook;

  return (
    <>
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-white">Overall</span>
        <ChipBadge chip={statusChip(report.status)} />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Timers fresh" value={`${s.okTimers}/${s.totalTimers}`} />
        <Stat label="Quiet families" value={s.silentFamilies} sub="daily, froze nothing" />
        <Stat label="Problems" value={s.problemCount} />
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-[11px] uppercase tracking-wider text-slate-500">Order books</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-3xl font-black tracking-tight text-white">
              {formatAge(ob.newest_file_age_seconds)}
            </span>
            <ChipBadge chip={statusChip(ob.status)} />
          </div>
        </div>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">Timers</h2>
        <div className="flex flex-col gap-2">
          {timers.map((t) => (
            <div
              key={t.name}
              className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
            >
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-200">
                  {t.label} <span className="font-mono text-[11px] text-slate-500">({t.name})</span>
                </div>
                <div className="text-xs text-slate-500">{t.lastSuccess ?? "never"}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-sm tabular-nums text-slate-300">{t.age}</span>
                <ChipBadge chip={t.chip} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">
          Forecasts frozen (last {report.frozen_window_hours}h)
        </h2>
        <div className="flex flex-col gap-2">
          {families.length === 0 ? (
            <p className="text-sm text-slate-500">No families reported.</p>
          ) : (
            families.map((f) => (
              <div
                key={f.name}
                className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-200">{f.name}</div>
                  <div className="text-xs text-slate-500">{f.cadence}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-sm tabular-nums text-slate-300">{f.frozen}</span>
                  {f.silent ? <ChipBadge chip={{ label: "Quiet", tone: "bad" }} /> : null}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      {report.problems.length > 0 ? (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">Problems</h2>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-amber-200">
            {report.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="pb-6 text-xs text-slate-600">Generated {report.generated_at}</p>
    </>
  );
}
