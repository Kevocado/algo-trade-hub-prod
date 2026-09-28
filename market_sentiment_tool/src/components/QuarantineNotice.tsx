import { FlaskConical, ShieldAlert, AlertOctagon } from "lucide-react";

import {
  QUARANTINE_MARK,
  engineText,
  headlineCount,
  headlineReason,
  quarantineText,
  rowKindLabel,
  type QuarantineResponse,
  type QuarantineRow,
} from "@/lib/quarantine";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The quarantine surface: what the repaired-but-unpublished engines measured, marked as such.
 *
 * This is the second sink's visible half, and it is what PR #38's report asked for and could not
 * have built: a place where the owner can see what Weather and Macro *would do* without a single
 * row being published. The engines were repaired on 2026-09-28 -- they had been reading a Kalshi
 * quote field the API stopped sending, so every market looked like a 0c quote and every one was
 * skipped -- and they now produce 295 rows a scan that go to `kalshi_quarantine_edges` and nowhere
 * else.
 *
 * **The headline is 26, not 295, and the component is built so it cannot be anything else.** It
 * renders `headlineCount`, which is `independent_opportunities`; the row total, the restatement
 * count and the artefact count are all shown beside it, in that order, because the reader's question
 * is "how much of this is real" and the answer is a ratio rather than a number. A card reading
 * "295 opportunities" would be the same class of failure as PR #38's "No high-confidence edges
 * detected in weather": a confident number about a search that did not happen in the sense the
 * reader will take it to have happened.
 *
 * The marker is not decoration and is not optional. It is on the heading, on the note, and beside
 * the headline, so a reader who screenshots any single figure still has QUARANTINED in the image. A
 * quarantined number that travels alone is indistinguishable from a published one.
 *
 * Three empty states, and the order is the content:
 *
 *   read failed   nothing is claimed at all. Not "no opportunities" -- a 500 on this endpoint must
 *                 not read as a quiet market, which is PR #38's defect one layer up.
 *   not measured  the sink is empty. Either no scan has written to it or the migration is not
 *                 applied, and which one it is has to be said rather than inferred from a zero.
 *   measured      the counts, and the note.
 */
export interface QuarantineNoticeProps {
  payload: QuarantineResponse | null;
  /** A failed read of the quarantine. When set, nothing is claimed about what was measured. */
  readError?: string | null;
  className?: string;
}

/** One row, with its classification on it. Never rendered without the marker. */
function QuarantineRowCard({ row }: { row: QuarantineRow }) {
  const kind = rowKindLabel(row);
  const price = row.price_cents === null ? NOT_MEASURED : `${row.price_cents}c`;
  const model = row.model_probability_pct === null ? NOT_MEASURED : `${row.model_probability_pct}%`;

  return (
    <li className="rounded-lg border border-amber-800/40 bg-amber-950/10 p-3 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-bold text-amber-200 truncate">{row.title || row.market_id}</span>
        <span className="shrink-0 rounded-full border border-amber-600/40 bg-amber-500/10 px-2 py-0.5 text-[9px] font-bold tracking-widest text-amber-300">
          {QUARANTINE_MARK}
        </span>
      </div>
      <p className="font-mono text-[10px] text-amber-100/50">{row.market_id}</p>
      <p className="text-xs text-amber-100/80">
        <span className="font-bold">{row.action ?? "—"}</span> at {price} · model {model} · edge{" "}
        {row.edge_points === null ? NOT_MEASURED : `${row.edge_points}`}
      </p>
      {kind && <p className="text-[10px] uppercase tracking-wider text-amber-300/70">{kind}</p>}
      {/* The forecast key, so a reader can see which other rows are the same statement. This is the
          difference between "138 GDP rows" and "138 rows that are four opinions", and it is the
          only way the restatement count can be checked from the page. */}
      {row.forecast_key && (
        <p className="font-mono text-[9px] text-amber-100/40">forecast: {row.forecast_key}</p>
      )}
    </li>
  );
}

export function QuarantineNotice({ payload, readError = null, className = "" }: QuarantineNoticeProps) {
  if (readError) {
    return (
      <section
        aria-label="Quarantine measurement could not be read"
        data-testid="quarantine-read-failure"
        className={`rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 ${className}`}
      >
        <div className="flex items-center gap-2">
          <AlertOctagon className="h-4 w-4 text-rose-400" aria-hidden="true" />
          <h2 className="text-sm font-bold uppercase tracking-widest text-rose-200">
            Could not read what the quarantined engines measured
          </h2>
        </div>
        <p className="mt-1 text-xs text-rose-100/80">{readError}</p>
        <p className="mt-1 text-xs text-rose-100/70">
          This is a failed read, not an empty one. Nothing is claimed here: not that the engines found
          opportunities, and not that they found none.
        </p>
      </section>
    );
  }

  if (!payload) {
    return (
      <section
        aria-label="Quarantine measurement did not arrive"
        data-testid="quarantine-missing"
        className={`rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 ${className}`}
      >
        <p className="text-sm font-bold uppercase tracking-widest text-amber-200">
          Quarantine measurement did not arrive
        </p>
        <p className="mt-1 text-xs text-amber-100/70">
          Nothing is claimed about what the Weather and Macro engines would have published. That is
          not established until the measurement arrives.
        </p>
      </section>
    );
  }

  // Empty sink. The distinction that matters: an empty table is either no scan yet or a migration
  // that has not been applied, and NEITHER is a count of zero opportunities. The server sends the
  // reason; this renders it rather than substituting a number.
  if (!payload.measured || !payload.totals) {
    return (
      <section
        aria-label="Quarantine has not measured anything yet"
        data-testid="quarantine-unmeasured"
        className={`rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 ${className}`}
      >
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-400" aria-hidden="true" />
          <h2 className="text-sm font-bold uppercase tracking-widest text-amber-200">
            {QUARANTINE_MARK} — nothing measured yet
          </h2>
        </div>
        <p className="mt-1 text-xs text-amber-100/70">{payload.unmeasured_reason}</p>
      </section>
    );
  }

  const reason = headlineReason(payload);

  return (
    <section
      aria-label={`${QUARANTINE_MARK}: what the repaired Weather and Macro engines measured`}
      data-testid="quarantine-notice"
      className={`rounded-xl border border-amber-600/50 bg-amber-950/20 p-4 ${className}`}
    >
      <div className="flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-amber-400" aria-hidden="true" />
        <h2 className="text-sm font-bold uppercase tracking-widest text-amber-200">
          {QUARANTINE_MARK} — what Weather and Macro would have published
        </h2>
      </div>

      <p className="mt-1 text-xs text-amber-100/80">{payload.note}</p>

      <div className="mt-3 flex flex-wrap items-baseline gap-4">
        {/* The headline, and only ever the independent count. `headlineCount` returns a dash rather
            than a 0 if the measurement is missing, so this element cannot print a number nobody
            measured even if the payload shape changes under it. */}
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-amber-300/70">
            Independent opportunities
          </p>
          <p className="text-3xl font-black text-amber-200" data-testid="quarantine-headline">
            {headlineCount(payload)}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-amber-300/70">
            Rows measured
          </p>
          <p className="text-2xl font-black text-amber-100/70" data-testid="quarantine-rows">
            {payload.totals.rows}
          </p>
        </div>
      </div>

      {reason && <p className="mt-2 text-xs leading-relaxed text-amber-100/80">{reason}</p>}

      <p className="mt-2 text-[10px] uppercase tracking-wider text-amber-200/60">{quarantineText(payload)}</p>

      {payload.engines.length > 0 && (
        <ul className="mt-2 space-y-1">
          {payload.engines.map((rollup) => (
            <li key={rollup.engine ?? "(unattributed)"} className="text-xs text-amber-100/80">
              <span className="font-mono font-bold">{engineText(rollup)}</span>
            </li>
          ))}
        </ul>
      )}

      {/* The proof, on the page, in the place a reader who doubts the label will look. Not a claim
          about tonight's scan: a hard zero by construction, because there is no code path from a
          quarantined row to the trade-proposal sink. */}
      <p className="mt-3 border-t border-amber-800/40 pt-2 text-[11px] font-bold text-amber-300">
        Rows written to kalshi_edges: {payload.kalshi_edges_written} · sink: {payload.sink}
      </p>

      {payload.rows_page.length > 0 && (
        <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
          {payload.rows_page.map((row) => (
            <QuarantineRowCard key={row.market_id} row={row} />
          ))}
        </ul>
      )}
    </section>
  );
}

export { NOT_MEASURED };
export default QuarantineNotice;
