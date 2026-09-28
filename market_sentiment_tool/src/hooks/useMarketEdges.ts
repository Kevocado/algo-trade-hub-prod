import { useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import { EDGES_READ_LIMIT, partitionDisplayOnly, type WithheldEdge } from "@/lib/displayOnlyEngines";

export interface KalshiEdge {
  id: string;
  market_id: string;
  edge_type: 'WEATHER' | 'MACRO' | 'SPORTS' | 'CRYPTO' | 'ENERGY';
  engine?: string | null;
  gate_status?: 'SHADOW' | 'PROMOTED' | null;
  market_url?: string | null;
  title?: string;
  market_title?: string;
  market_prob: number;
  our_prob: number;
  edge_pct: number;
  discovered_at: string;
  raw_payload: any;
  ui_reasoning?: boolean;
  ai_summary?: string;
}

/**
 * How many rows this read takes, and whether more are behind it. The constant is a policy number
 * shared with the copy (`displayOnlyEngines`), because a count of this read is not a count of the
 * table and the page has to be able to say which one it is printing.
 */
export { EDGES_READ_LIMIT };

export const useMarketEdges = () => {
  const [edges, setEdges] = useState<KalshiEdge[]>([]);
  // Rows deliberately NOT presented as opportunities, each with the reason why. See
  // lib/displayOnlyEngines: cpi_nowcast is display-only, and withholding its rows silently would
  // be indistinguishable from the engine never having existed. A caller that renders nothing for
  // this bucket makes the filter silent; the count is exposed so an empty bucket is visible rather
  // than inferred.
  //
  // The historical cpi_nowcast rows stay in kalshi_edges while their markets are open --
  // `remove_closed_cpi_edges` (tradehub/scripts/scan.py) deletes each one on the first hourly
  // scan after `expires_at`, so a closed market's rows are lifecycle-cleaned like every other
  // engine's. The filter is a standing rule over the rows that are still there, not a promise that
  // the rows are permanent, and nothing may state otherwise.
  const [withheld, setWithheld] = useState<WithheldEdge<KalshiEdge>[]>([]);
  const [loading, setLoading] = useState(true);
  /**
   * A failed read, or null when the last read succeeded.
   *
   * This exists because an empty result used to be indistinguishable from an unobserved one. A
   * swallowed Supabase error left `edges: []` and `withheld: []`, so a page rendered "no edges" and
   * the notice rendered nothing at all -- which reads as "nothing was withheld", the one thing
   * the withholding rule exists to make reliable. So the failure is state, not a `console.error`,
   * and both buckets are emptied: a stale successful read left beside a failed one would be
   * worse than either, because it would be attributed to the current state.
   */
  const [error, setError] = useState<string | null>(null);
  /**
   * Whether the read hit `EDGES_READ_LIMIT` with rows behind it. Determined by asking for one row
   * more than the limit and keeping the extra, so "there are more" is something the read
   * established rather than something it inferred from filling the cap. This is the same trick
   * `/api/cpi-display` uses for its own `truncated`.
   */
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    const fetchEdges = async () => {
      try {
        const { data, error } = await supabase
          .from("kalshi_edges")
          .select("*")
          .order("discovered_at", { ascending: false })
          .limit(EDGES_READ_LIMIT + 1);

        if (error) throw error;

        // Normalize edge pct
        const read = data ?? [];
        // The +1 row is the sentinel, not data. It is dropped before anything can count it.
        const hasMore = read.length > EDGES_READ_LIMIT;
        const normalized = read.slice(0, EDGES_READ_LIMIT).map(d => ({
            ...d,
            our_prob: d.our_prob ?? (d.raw_payload?.my_prob ? d.raw_payload.my_prob / 100 : 0),
            market_prob: d.market_prob ?? (d.raw_payload?.yes_ask ? d.raw_payload.yes_ask / 100 : 0),
            edge_pct: d.edge_pct ?? d.raw_payload?.edge ?? 0
        }));

        // Split AFTER the read, not in the query. Two reasons. A `.neq("engine", ...)` filter
        // excludes NULL engines in PostgREST, which would silently drop every row written before
        // the `engine` column existed -- a row disappearing for a reason nobody wrote down. And a
        // query filter is also a silent filter: it cannot say how many rows it removed.
        const split = partitionDisplayOnly(normalized);
        setEdges(split.edges);
        setWithheld(split.withheld);
        setTruncated(hasMore);
        setError(null);
      } catch (err) {
        console.error("Error fetching kalshi_edges:", err);
        // Cleared, not left standing. A count from the previous successful read is a claim about
        // the current one, and a page rendering it next to a fresh failure has been told
        // something false.
        setEdges([]);
        setWithheld([]);
        setTruncated(false);
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchEdges();

    const channel = supabase
      .channel("kalshi_edges_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "kalshi_edges" },
        (payload) => {
          console.log("Realtime kalshi_edges update:", payload);
          fetchEdges(); // Just refetch for simplicity in God-Mode
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return { edges, withheld, loading, error, truncated };
};
