import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { buildApiUrl } from "@/lib/api";
import {
  cpiCoverageNote,
  cpiGateNote,
  cpiHeadline,
  cpiRowNote,
  cpiTruncationNote,
  hoursText,
  nowcastMeasure,
  probMeasure,
  sigmaText,
  statusText,
  stampText,
  suggestOnlyNote,
  type CpiDisplayResponse,
  type CpiDisplayRow,
  type Measure,
} from "@/lib/cpiDisplay";

/**
 * CPI, shown for context. Not an edge engine, and this page says so in its heading, in the reason
 * above the table, in the gate line, and in every row -- because a model probability beside a market
 * price reads as an opportunity everywhere else in finance, and one heading does not overcome that.
 *
 * The four claims the endpoint makes about itself are rendered here, and each of them is a claim a
 * reader would otherwise have to assume:
 *
 *   * the gate was NEVER CHECKED, rather than checked and declined (`gate_checked: false`). Section
 *     5 records CPI as REFUTED, not pending, and a pending engine is a live opportunity in
 *     everything but name. `GateBadge` is deliberately NOT used here: it renders "Shadow: this
 *     engine has not passed the promotion gate yet", which is exactly the pending reading.
 *   * the read was TRUNCATED, rather than quietly showing the newest 200 rows as if they were all
 *     of them;
 *   * the rows WITHHELD FROM THE COMPARISON, counted over the whole read, each with its reason;
 *   * and, underneath all of it, a figure the scan did not record is rendered as words. Never as 0,
 *     never as 0.0, never as a dash standing in for one.
 */

/** A figure, or the words saying why there isn't one. Never a placeholder number. */
function Figure({ measure }: { measure: Measure }) {
  if (measure.known) return <>{measure.value}</>;
  return (
    <span className="text-xs not-italic text-slate-500" title={measure.note}>
      {measure.note}
    </span>
  );
}

const HEAD = ["Market", "Model", "Market mid", "Nowcast", "Ledger", "Why this is here"];

function Row({ row }: { row: CpiDisplayRow }) {
  const at = stampText(row.as_of);
  return (
    <tr className="border-t border-slate-800 align-top">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <div className="font-mono font-medium text-slate-100">{row.market_ticker ?? "ticker not reported"}</div>
        <div className="text-[10px] uppercase tracking-widest text-slate-500">{statusText(row.status)}</div>
      </th>
      <td className="py-2 pr-3 text-slate-300">
        <Figure measure={probMeasure(row.our_prob)} />
      </td>
      <td className="py-2 pr-3 text-slate-300">
        {/* A release with no quote has NO market probability. The reason travels with the row, so a
            blank cell cannot be read as a market that said zero. */}
        <Figure measure={probMeasure(row.market_prob, "no market mid recorded")} />
      </td>
      <td className="py-2 pr-3 text-slate-300">
        <Figure measure={nowcastMeasure(row.nowcast)} />
        {sigmaText(row.sigma) && (
          <span className="ml-1 text-xs text-slate-500">{sigmaText(row.sigma)}</span>
        )}
      </td>
      <td className="py-2 pr-3 text-xs text-slate-400">
        {at ? at : <span className="text-slate-500">time not reported</span>}
        <span className="block text-slate-500">
          <Figure measure={hoursText(row.hours_to_close)} />
        </span>
      </td>
      <td className="py-2 pr-3 text-xs text-slate-400">{cpiRowNote(row)}</td>
    </tr>
  );
}

export default function CpiDisplay() {
  const [data, setData] = useState<CpiDisplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(buildApiUrl("/api/cpi-display?limit=50"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (!cancelled) {
          setData(payload as CpiDisplayResponse);
          setError(null);
        }
      })
      .catch((err) => {
        // Never rendered as an empty board. "Not measured" and "measured, and there is nothing
        // there" are different facts, and the endpoint returns a 503 rather than an empty list so
        // the page can keep them apart.
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-3 p-8 text-slate-300">
        <Loader2 className="h-5 w-5 animate-spin text-amber-400" /> Loading the CPI nowcast
      </div>
    );
  }

  if (error) {
    return (
      <div className="m-8 rounded-lg border border-rose-500/30 bg-rose-500/10 p-6 text-rose-100">
        <p className="flex items-center gap-3 text-sm font-semibold">
          <AlertTriangle className="h-5 w-5 text-rose-400" /> CPI nowcast unavailable
        </p>
        <p className="mt-1 text-sm text-rose-200/90">{error}</p>
        <p className="mt-2 text-xs text-rose-200/70">
          This is a failed read, not an empty one: nothing below is being claimed about the nowcast,
          because nothing was measured.
        </p>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-slate-400">Loading the CPI nowcast…</div>;

  const headline = cpiHeadline(data);
  const gate = cpiGateNote(data);
  const truncation = cpiTruncationNote(data);
  const suggestOnly = suggestOnlyNote(data);

  return (
    <div className="p-8 space-y-8">
      <header className="border-b border-slate-900 pb-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-bold text-white">{headline.label}</h1>
          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-amber-300">
            mode: {data.mode}
          </span>
        </div>
        <p className="text-sm text-slate-400">
          {headline.value} · read as of {stampText(data.as_of) ?? "an unreported time"}
        </p>
      </header>

      {/* The reason sits ABOVE the table, not only inside each row, so it is read before the numbers
          rather than after them. */}
      <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
        <p className="font-semibold">Not an edge engine</p>
        <p className="mt-1 text-amber-200/90">{data.reason}</p>
        {suggestOnly && <p className="mt-1 text-xs text-amber-200/70">{suggestOnly}</p>}
      </div>

      {/* Obligation: the gate was never checked. The bare word SHADOW is deliberately absent -- it is
          the gate's own vocabulary and reads as a verdict that was reached, i.e. as pending. */}
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm">
        <p className="font-semibold text-slate-100">{gate.headline}</p>
        <p className="mt-1 text-xs text-slate-400">{gate.detail}</p>
      </div>

      {/* Obligation: the read is bounded, and a bounded read that reads as complete is a claim about
          the data. */}
      {truncation && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
          {truncation}
        </div>
      )}

      <p className="text-xs text-slate-500">{cpiCoverageNote(data)}</p>

      {data.rows.length === 0 ? (
        <p className="text-slate-400">
          No CPI markets in the ledger right now. The nowcast is published on a schedule, so an empty
          board between prints is expected rather than a fault.
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            CPI nowcast against the market, for context. This engine is not an edge engine and no
            edge is shown; rows without a recorded market mid are not comparisons.
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
          <tbody>
            {data.rows.map((row, i) => (
              <Row key={row.market_ticker ?? `row-${i}`} row={row} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
