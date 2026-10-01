import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { GateBadge } from "@/components/GateBadge";
import { SettledBars } from "@/components/SettledBars";
import {
  backtestGateLabel,
  brierVerdict,
  formatBrier,
  formatCount,
  formatSimulatedMoney,
  summarise,
  type ScoreboardResponse,
  type ScoreboardRow,
} from "@/lib/scoreboard";

/**
 * Should I trust this engine?
 *
 * This is the question the product turns on, and every other page is downstream of it. So the
 * numbers are shown without softening: each engine's Brier beside the market's, the multiple
 * between them, the simulated loss, and both bars it has to clear.
 *
 * Three things this page will not do, each because the alternative reads as something it is not:
 *
 *   1. It will not show the headline without the count of rows that were never compared. The
 *      headline is a claim about ENGINES and that count is about ROWS, so on a 3-of-5-comparable
 *      board the sentence is true and incomplete -- and only rendering the count together with it
 *      puts the incompleteness in front of the reader. `summarise` hands both over as one pair and
 *      they are drawn in one block.
 *   2. It will not drop or soften a losing engine. There is no filter, no sort control and no
 *      summary that names only the best engine. Every row the API returns is drawn, in the order
 *      the API returned it.
 *   3. It will not merge the two gates. `gate_status` is what `check_promotion_gate` returned when
 *      the run was recorded, which never consulted the track record; `promotion_status` is the
 *      shared lookup's full verdict, keyed on (engine, engine_version). A column reading "promoted"
 *      off the first one would tell a human an edge is tradable when the gate has not said so.
 *
 * And one it would otherwise fail silently, which is the reduction itself. `is_experiment_version`
 * fails toward EXCLUSION, so a version string that trips it -- a future `gas-v1-leading-edge`, a
 * typo, a stray space -- drops that engine off the board while the headline keeps reading
 * confidently. An absent engine reads as "this engine has nothing to show", which is a claim about
 * the engine. So the summary carries `runs_read` and `engines`: enough to see that N runs were read
 * and M rows are on the board, which is what makes a reduced board distinguishable from a complete
 * one. The excluded versions are NOT listed. An experiment is absent because the two runs disagree
 * about the engine, and a footnote is something a reader skips; the count of a reduction is a
 * different claim, because it carries no run's numbers and therefore no record for a reader to
 * mistake for one.
 *
 * The route is `/scoreboard` and the name is "Engine Scoreboard", and both of those were arrived at
 * on 2026-09-28. The owner went to `/shadow` looking for this page and got a 503 from the crypto
 * shadow-timeline backtester, which is a different thing that happened to share a word.
 *
 * The name is "Engine Scoreboard" rather than "Shadow Scoreboard" -- the name the owner's approval
 * used -- because "shadow" already means two OTHER things in this product (the crypto timeline, and
 * the not-promoted gate status that every unread engine carries) and this page is about neither.
 * The approval string still works: `/shadow-scoreboard` is a permanent redirect to here, so the
 * name people will type resolves without being the canonical name. An earlier revision of this
 * branch made that string the route, which put the ambiguity somewhere expensive to change.
 * `/shadow` keeps its own route and is NOT redirected here — see `App.tsx` for why swapping those
 * two would be a second lie.
 *
 * Nothing here computes a threshold, a gate or a rounding policy -- all of that is
 * `tradehub/scoreboard.py` and rides in on the response. This file decides layout and nothing else.
 */

/** One scoreboard row. The two bars are `@/components/SettledBars`, shared with `/models`. */
function Row({ row }: { row: ScoreboardRow }) {
  return (
    <tr className="border-t border-slate-800 align-top">
      <th scope="row" className="py-3 pr-3 text-left font-normal">
        <div className="font-medium text-slate-100">{row.engine}</div>
        <div className="text-xs text-slate-500">
          {row.mode}
          {row.engine_version ? ` · ${row.engine_version}` : ""}
        </div>
        {row.date_from && row.date_to && (
          <div className="text-[11px] text-slate-600">
            {row.date_from.slice(0, 10)} → {row.date_to.slice(0, 10)}
          </div>
        )}
      </th>
      <td className="py-3 pr-3 font-mono text-slate-200">{formatBrier(row.brier_ours)}</td>
      <td className="py-3 pr-3 font-mono text-slate-400">{formatBrier(row.brier_market)}</td>
      <td className="py-3 pr-3 text-slate-300">
        {brierVerdict(row)}
        <div className="text-[11px] text-slate-500">
          {formatCount(row.n_decisions)} decisions · {formatCount(row.n_fills)} filled
        </div>
      </td>
      {/* Labelled as simulated: this product places no orders, so a currency figure with no such
          label would read as money available to someone. */}
      <td className="py-3 pr-3 font-mono text-slate-300">
        {formatSimulatedMoney(row.pnl_after_fees)}
        <div className="text-[11px] text-slate-500">
          drawdown {formatSimulatedMoney(row.max_drawdown)}
        </div>
      </td>
      <td className="py-3 pr-3">
        <SettledBars row={row} />
      </td>
      <td className="py-3 pr-3">
        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Backtest gate
        </div>
        <div className="text-[11px] text-slate-300">{backtestGateLabel(row.gate_status)}</div>
        <div className="mt-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Promotion
        </div>
        {/* The scope, in the cell and in VISIBLE TEXT, naming the pair rather than "this".

            Two reasons it is not prose in a comment, which is what it was before the review found it:
            a reader who has not opened the code has no other way to know the verdict is about this
            engine AND this version, and two versions of one engine carry the same verdict, so a
            bare "Promotion" reads as the engine's. It is not in the badge's `title=` either: that is
            a native tooltip on a <div> with no tabindex, no role and no aria-describedby, so it
            cannot be reached by keyboard and is never announced. The scope is the one claim in this
            cell that a mouse-only affordance would take away from everyone else.

            10px is deliberate and is the size this cell's own headers already use, not a leftover:
            there is no 12px floor in this repo, and 10px is this file's convention -- the two
            micro-headers in this cell, each bar's own label, and the shared `GateBadge` below. (No
            count is quoted here, because a comment that quoted the class name would inflate it.)
            The claim is carried by sentence case, not by size -- `uppercase` would have case-folded
            `gas-v1` into a different string than the one the lookup is keyed on.

            `—` rather than a guess: the API's `is_experiment_version` fails toward EXCLUSION, so a
            run with an absent or empty version never reaches this table and the dash is a guard for
            the type, not a state a reader will see. */}
        <div className="text-[10px] text-slate-500">
          for {row.engine} · {row.engine_version ?? "—"}
        </div>
        {/* The shared lookup's verdict, for the engine and version named above. */}
        <GateBadge edge={{ gate_status: row.promotion_status }} />
        {row.gate_reasons.length > 0 && (
          <ul className="mt-2 list-disc pl-4 text-[11px] text-slate-500">
            {row.gate_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

const HEAD = [
  "Engine",
  "Brier (ours)",
  "Brier (market)",
  "Against the market",
  "Simulated (backtest)",
  "Distance to the gate",
  "Gate",
];

const TONES = {
  behind: "border-amber-900/60 bg-amber-950/20 text-amber-100",
  ahead: "border-emerald-900/60 bg-emerald-950/20 text-emerald-100",
  unknown: "border-slate-800 bg-slate-900/40 text-slate-300",
} as const;

export default function Scoreboard() {
  const [data, setData] = useState<ScoreboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/scoreboard"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        setData(payload as ScoreboardResponse);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Engine scoreboard unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
          {/* The API names the table and the migration that creates it, so the page shows what it
              was told. A second copy of that mapping here would be a second place to be wrong. */}
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-slate-400">Loading engine scoreboard…</div>;

  const summary = summarise(data);

  return (
    <div className="p-8 space-y-6">
      <header className="border-b border-slate-900 pb-4">
        <h1 className="text-2xl font-bold text-white">Engine scoreboard</h1>
        <p className="mt-2 text-sm text-slate-400">
          Each engine&apos;s error next to the market&apos;s, on the same decisions. Lower is better. Money is a
          simulated backtest, not a balance.
        </p>
      </header>

      {/* The headline, the count that qualifies it, and the count of the reduction, in one block.
          Rendered together or not at all: a sentence about engines next to an unstated count of
          unmeasured rows is a claim the board has not earned -- and `runs_read` beside `rows_total`
          is the only thing that distinguishes a complete board from one an engine has silently
          vanished from. The excluded versions are NOT listed; only the size of the reduction is. */}
      <div className={`rounded-lg border p-4 text-sm ${TONES[summary.tone]}`}>
        <p className="font-semibold">{summary.headline}</p>
        <p className="mt-1 text-xs opacity-90">{summary.counts}</p>
        {summary.caveat && <p className="mt-1 text-xs opacity-90">{summary.caveat}</p>}
        {data.promotion_lookup_failed && (
          <p className="mt-2 text-xs text-amber-300">
            The promotion gate could not be read, so every engine below reads SHADOW. That is the
            fail-closed default, not a measurement.
          </p>
        )}
      </div>

      {data.rows.length === 0 ? (
        <p className="text-slate-400">
          No recorded backtest runs yet. Run{" "}
          <code>python -m tradehub.scripts.backtest_engines --engine &lt;engine&gt; --record</code> to
          produce one.
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            Per-engine Brier against the market, both bars of its settled distance, and both gates.
          </caption>
          <thead>
            <tr className="border-b border-slate-800">
              {HEAD.map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="py-2 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          {/* Every row the API returned, in the API's order. No filter, no sort, no tail collapsed:
              this page exists to show the losing tail. */}
          <tbody>
            {data.rows.map((row) => (
              <Row key={`${row.engine}-${row.mode}-${row.engine_version}`} row={row} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
