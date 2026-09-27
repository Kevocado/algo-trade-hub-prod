import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { GateBadge } from "@/components/GateBadge";
import {
  TIER_LABELS,
  formatEdgePct,
  groupByTier,
  rejectReasonLabel,
  type SportsEdge,
  type SportsEdgesResponse,
} from "@/lib/sportsEdges";

/**
 * One sports edge row.
 *
 * The three numbers on the old row were each correct and none of them meant what the row implied:
 *
 *     UConn wins   YES @ 18c   78% vs 33%   +59.3 pp
 *
 * `edge_pct` is the after-fee edge against the ENTRY price on the chosen side (18c). `market_prob`
 * is the quote MID (33c). Set side by side they invite `78 - 33 = 45`, which is not the 59.3 shown.
 * And that quote is 30c wide, which is why the row carries `wide_quote` as a reject reason -- on
 * every one of the 100 live rows. The "edge" WAS the spread.
 *
 * So: a row the filter rejected shows no headline number at all, the comparison that IS being made
 * is labelled, and the quote spread is shown because it is the thing that explains the number.
 */
function EdgeRow({ edge }: { edge: SportsEdge }) {
  const spread =
    typeof edge.quote_spread === "number" ? `${(edge.quote_spread * 100).toFixed(0)}¢` : null;
  const wide = typeof edge.quote_spread === "number" && edge.quote_spread >= 0.05;

  return (
    <tr className="border-t border-slate-800 align-top">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <div className="font-medium text-slate-100">{edge.away} @ {edge.home}</div>
        <div className="text-xs text-slate-500">{new Date(edge.start_utc).toLocaleString()}</div>
      </th>
      <td className="py-2 pr-3 text-slate-300">{edge.title}</td>
      <td className="py-2 pr-3 uppercase text-slate-300">
        {edge.side} @ {Math.round(edge.entry_price * 100)}¢
        {/* The spread is the reason a wide quote can manufacture an "edge" larger than the model's
            actual disagreement, so it sits next to the entry price it is compared against. */}
        {spread && (
          <div className={`text-[11px] ${wide ? "text-amber-400" : "text-slate-500"}`}>
            {spread} spread
          </div>
        )}
      </td>
      <td className="py-2 pr-3 text-slate-300">
        {Math.round(edge.our_prob * 100)}% model
        <span className="block text-xs text-slate-500">
          {Math.round(edge.market_prob * 100)}% market mid
        </span>
      </td>
      <td className="py-2 pr-3">
        {/* Withheld on a rejected row, so a spread artifact can never read as an opportunity. */}
        {edge.edge_pct === null || edge.edge_pct === undefined ? (
          <span className="text-slate-600" title="Withheld: the candidate filter rejected this row">
            &mdash;
          </span>
        ) : (
          <>
            <span className="font-semibold text-emerald-400">{formatEdgePct(edge.edge_pct)}</span>
            <span className="block text-[11px] text-slate-500">
              after fees vs {Math.round(edge.entry_price * 100)}¢ entry
            </span>
          </>
        )}
      </td>
      <td className="py-2 pr-3 text-xs text-slate-400">
        {edge.review?.drivers.map((d) => <div key={d}>• {d}</div>)}
        {edge.review?.red_flags.map((f) => <div key={f} className="text-amber-400">⚠ {f}</div>)}
        {edge.reject_reasons.map((r) => <div key={r}>{rejectReasonLabel(r)}</div>)}
      </td>
      <td className="py-2 pr-3">
        {/* Sports edges are gated per (engine, engine_version) like every other engine. */}
        <GateBadge edge={edge} />
        {/* A placeholder version is shown as nothing. The live page printed the bare word "unknown"
            under all 100 rows, which reads as a bug rather than as "not reported yet". */}
        {edge.engine_version && (
          <div className="mt-1 text-[10px] text-slate-500" title="Predictor snapshot this edge was priced from">
            {edge.engine_version.replace(/^feed:/, "")}
          </div>
        )}
      </td>
      <td className="py-2 text-xs">
        <a className="text-emerald-400 hover:underline" href={edge.market_url} target="_blank" rel="noreferrer">Kalshi</a>
        {" · "}
        <a className="text-sky-400 hover:underline" href={edge.source_url} target="_blank" rel="noreferrer">Predictor</a>
      </td>
    </tr>
  );
}

const HEAD = ["Game", "Market", "Side & spread", "Probability", "Edge after fees", "Why not", "Gate", "Links"];

export default function SportsEdges() {
  const [data, setData] = useState<SportsEdgesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sport, setSport] = useState<"" | "nfl" | "cfb">("");
  const [page, setPage] = useState(0);
  const pageSize = 50;

  useEffect(() => {
    const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
    if (sport) params.set("sport", sport);
    fetch(buildApiUrl(`/api/sports-edges?${params.toString()}`))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        setData(payload as SportsEdgesResponse);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, [sport, page]);

  if (error) return <div className="p-8 text-red-400">Sports edges unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading sports edges…</div>;

  const card = data.reviewer_scorecard;
  const shown = data.edges.length;
  const lastPage = Math.max(0, Math.ceil(data.total / pageSize) - 1);
  const groups = groupByTier(data.edges);
  // From the API, over the whole filtered set. Was derived from `groups`, i.e. from the current
  // page -- correct on page 1 by luck and wrong on every page after it, because ranking puts
  // candidates first and so page 2+ is always the reject tail.
  const candidateCount = data.candidate_count;
  const noCandidates = candidateCount === 0;

  return (
    <div className="p-8 space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-white">Sports edges</h1>
        <p className="text-sm text-slate-400">
          Suggestions only. Probabilities come from the NFL/CFB predictor sites&apos; frozen pre-game
          snapshots; the reviewer never changes them. Reviewer check: {card.approved.n} approved vs{" "}
          {card.rejected.n} rejected settled picks ({card.n_settled}/{card.min_settled} needed), verdict{" "}
          <b>{card.verdict}</b>.{" "}
          {/* Which ranking ordered the table, stated rather than implied. The score is
              edge / sigma, and sigma is null on every game the feed publishes today, so the sort
              falls back to raw edge -- and a page that says "ranked by confidence" while ranking
              by raw edge is worse than one that never claimed it. The edge_sigma sentence covers
              the partly-published case too: the score is per row, so rows whose feed carries no
              sigma are still ranked on their raw edge. */}
          {data.ranking === "edge_sigma"
            ? "Ranked by edge over the predictor's own sigma wherever the feed publishes one, and by raw edge for the rest."
            : "Ranked by raw edge: the feed reports no sigma yet, so there is no confidence to rank on."}
        </p>
      </header>

      {noCandidates && (
        // The honest empty state. The alternative -- the default view being a wall of rejected rows --
        // is what this page was, and it read as "nothing here" while showing 100 numbers.
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
          <p className="font-semibold text-slate-100">No pick currently passes the filter.</p>
          <p className="mt-1 text-slate-400">
            {" "}
            {data.total} upcoming sports markets were priced and none of the {data.total} passed. An edge
            is only surfaced once it is tradeable (a tight quote with real size behind it), lands inside
            the decision window, and comes from a predictor that is calibrated in that price bucket.
            The reason each one failed is in the table below, and the gate stays in shadow until there
            are enough settled results to judge it.
          </p>
        </div>
      )}

      <div className="flex items-center gap-3 text-sm">
        <label className="text-slate-400" htmlFor="sports-sport">Sport</label>
        <select
          id="sports-sport"
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200"
          value={sport}
          onChange={(e) => { setSport(e.target.value as "" | "nfl" | "cfb"); setPage(0); }}
        >
          <option value="">All</option>
          <option value="nfl">NFL</option>
          <option value="cfb">CFB</option>
        </select>
        <span className="text-slate-500">
          Showing {data.offset + (shown ? 1 : 0)}–{data.offset + shown} of {data.total}
        </span>
        <button
          className="px-2 py-1 rounded border border-slate-700 text-slate-300 disabled:opacity-40"
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
        >
          Previous
        </button>
        <button
          className="px-2 py-1 rounded border border-slate-700 text-slate-300 disabled:opacity-40"
          disabled={page >= lastPage}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>

      {groups.map((group) => (
        <section key={group.tier}>
          <h2 className="mb-2 text-lg font-semibold text-slate-200">{TIER_LABELS[group.tier]} ({group.edges.length})</h2>
          <table className="w-full text-sm">
            {/* The table had no header row at all, so every column was unnamed to a screen reader. */}
            <caption className="sr-only">
              Sports edges, grouped by tier. An edge is shown only once it passes the candidate filter.
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
            <tbody>{group.edges.map((edge) => <EdgeRow key={edge.market_id} edge={edge} />)}</tbody>
          </table>
        </section>
      ))}
      {shown === 0 && <p className="text-slate-400">No upcoming sports edges.</p>}
    </div>
  );
}
