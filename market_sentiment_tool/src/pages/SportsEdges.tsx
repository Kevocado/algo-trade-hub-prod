import { useEffect, useState } from "react";

import { Chip } from "@/components/Chip";
import { Stat } from "@/components/Stat";
import { buildApiUrl } from "@/lib/api";
import type { SportsEdge, SportsEdgesResponse } from "@/lib/sportsEdges";
import { board, gapText, type SportsPick } from "@/lib/sportsPicks";

/**
 * /sports: where the NFL and college-football predictors and the Kalshi market disagree, one pick per game.
 *
 * The reviewer decides what is featured, not the size of the gap: a pick is a "top pick" only if the
 * reviewer passed it, and a huge gap (model far from market) is listed under "flagged" with the gap
 * shown, never promoted. When nothing passes, the page says so instead of filling the screen.
 */

const PAGE = 200;

async function fetchAll(sport: string): Promise<SportsEdge[]> {
  const edges: SportsEdge[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (sport) params.set("sport", sport);
    const response = await fetch(buildApiUrl(`/api/sports-edges?${params}`));
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
    const page = payload as SportsEdgesResponse;
    edges.push(...page.edges);
    if (edges.length >= page.total || page.edges.length === 0) return edges;
  }
}

const WHEN = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

function PickRow({ pick }: { pick: SportsPick }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 border-t border-slate-800 py-3 lg:grid-cols-[1.4fr_1fr_auto]">
      <div>
        <div className="font-medium text-slate-100">{pick.call}</div>
        <div className="text-xs text-slate-500">
          {pick.matchup} · {WHEN.format(new Date(pick.startUtc))}
          {pick.kind !== "winner" && <span> · {pick.kind}</span>}
        </div>
      </div>
      <div className="hidden text-sm tabular-nums text-slate-300 lg:block">
        Model <b className="text-slate-100">{pick.model}%</b> <span className="text-slate-600">·</span> Market{" "}
        <b className="text-slate-100">{pick.market}%</b>
      </div>
      <div className="flex items-center gap-3 justify-self-end">
        <Chip tone={pick.largeGap ? "warn" : "good"} title={pick.largeGap ? "Model and market are unusually far apart" : "Model minus market, in points"}>
          {gapText(pick.gap)} pts
        </Chip>
        <a className="text-xs text-sky-400 hover:underline" href={pick.marketUrl} target="_blank" rel="noreferrer">Kalshi</a>
      </div>
      <div className="text-xs tabular-nums text-slate-400 lg:hidden">
        Model {pick.model}% · Market {pick.market}%
      </div>
    </li>
  );
}

function Section({ title, picks, initial = 6 }: { title: string; picks: SportsPick[]; initial?: number }) {
  const [all, setAll] = useState(false);
  if (picks.length === 0) return null;
  const shown = all ? picks : picks.slice(0, initial);
  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold text-slate-200">
        {title} <span className="text-slate-500">({picks.length})</span>
      </h2>
      <ul>{shown.map((p) => <PickRow key={p.key} pick={p} />)}</ul>
      {picks.length > initial && (
        <button type="button" className="mt-2 text-sm text-sky-400 hover:underline" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${picks.length}`}
        </button>
      )}
    </section>
  );
}

export default function SportsEdges() {
  const [edges, setEdges] = useState<SportsEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sport, setSport] = useState<"" | "nfl" | "cfb">("");

  useEffect(() => {
    setEdges(null);
    fetchAll(sport).then(setEdges).catch((e: Error) => setError(e.message));
  }, [sport]);

  if (error) return <div className="p-8 text-red-400">Sports picks unavailable: {error}</div>;
  if (!edges) return <div className="p-8 text-slate-400">Loading sports picks…</div>;

  const b = board(edges);
  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">Sports picks</h1>
          <p className="mt-2 text-slate-400">Where our predictors and the market disagree.</p>
        </div>
        <div role="group" aria-label="Sport" className="flex gap-2">
          {([["", "All"], ["nfl", "NFL"], ["cfb", "College"]] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={sport === value}
              onClick={() => setSport(value)}
              className={`rounded-full border px-3 py-1 text-sm ${
                sport === value ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-3">
        <Stat value={b.topPicks.length} label="top picks" />
        <Stat value={b.flagged.length} label="flagged by the reviewer" />
        <Stat value={b.unreviewed.length} label="not reviewed yet" />
      </section>

      {b.topPicks.length === 0 && (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-slate-300">No pick passed review today.</p>
      )}

      <Section title="Top picks" picks={b.topPicks} />
      <Section title="Flagged by the reviewer" picks={b.flagged} />
      <Section title="Not reviewed yet" picks={b.unreviewed} />

      {b.noEdge > 0 && <p className="text-sm text-slate-500">{b.noEdge} more games had no usable edge.</p>}
    </div>
  );
}
