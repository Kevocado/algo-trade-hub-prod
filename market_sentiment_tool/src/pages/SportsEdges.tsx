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

function EdgeRow({ edge }: { edge: SportsEdge }) {
  return (
    <tr className="border-t border-slate-800 align-top">
      <td className="py-2 pr-3">
        <div className="font-medium text-slate-100">{edge.away} @ {edge.home}</div>
        <div className="text-xs text-slate-500">{new Date(edge.start_utc).toLocaleString()}</div>
      </td>
      <td className="py-2 pr-3 text-slate-300">{edge.title}</td>
      <td className="py-2 pr-3 uppercase text-slate-300">{edge.side} @ {Math.round(edge.entry_price * 100)}¢</td>
      <td className="py-2 pr-3 text-slate-300">{Math.round(edge.our_prob * 100)}% vs {Math.round(edge.market_prob * 100)}%</td>
      <td className="py-2 pr-3 font-semibold text-emerald-400">{formatEdgePct(edge.edge_pct)}</td>
      <td className="py-2 pr-3 text-xs text-slate-400">
        {edge.review?.drivers.map((d) => <div key={d}>• {d}</div>)}
        {edge.review?.red_flags.map((f) => <div key={f} className="text-amber-400">⚠ {f}</div>)}
        {edge.reject_reasons.map((r) => <div key={r}>{rejectReasonLabel(r)}</div>)}
      </td>
      <td className="py-2 pr-3">
        {/* Sports edges are gated per (engine, engine_version) like every other engine. */}
        <GateBadge edge={edge} />
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
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, [sport, page]);

  if (error) return <div className="p-8 text-red-400">Sports edges unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading sports edges…</div>;

  const card = data.reviewer_scorecard;
  const shown = data.edges.length;
  const lastPage = Math.max(0, Math.ceil(data.total / pageSize) - 1);
  return (
    <div className="p-8 space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-white">Sports edges</h1>
        <p className="text-sm text-slate-400">
          Suggestions only. Probabilities come from the NFL/CFB predictor sites' frozen pre-game snapshots; the
          reviewer never changes them. Reviewer check: {card.approved.n} approved vs {card.rejected.n} rejected settled
          picks ({card.n_settled}/{card.min_settled} needed), verdict <b>{card.verdict}</b>.
        </p>
      </header>
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
      {groupByTier(data.edges).map((group) => (
        <section key={group.tier}>
          <h2 className="mb-2 text-lg font-semibold text-slate-200">{TIER_LABELS[group.tier]} ({group.edges.length})</h2>
          <table className="w-full text-sm">
            <tbody>{group.edges.map((edge) => <EdgeRow key={edge.market_id} edge={edge} />)}</tbody>
          </table>
        </section>
      ))}
      {shown === 0 && <p className="text-slate-400">No upcoming sports edges.</p>}
    </div>
  );
}
