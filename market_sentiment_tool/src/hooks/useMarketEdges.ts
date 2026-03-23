import { useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";

export interface KalshiEdge {
  id: string;
  market_id: string;
  edge_type: 'WEATHER' | 'MACRO' | 'SPORTS' | 'CRYPTO';
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

export const useMarketEdges = () => {
  const [edges, setEdges] = useState<KalshiEdge[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchEdges = async () => {
      try {
        const { data, error } = await supabase
          .from("kalshi_edges")
          .select("*")
          .order("discovered_at", { ascending: false })
          .limit(100);

        if (error) throw error;
        
        // Normalize edge pct
        const normalized = data?.map(d => ({
            ...d,
            our_prob: d.our_prob ?? (d.raw_payload?.my_prob ? d.raw_payload.my_prob / 100 : 0),
            market_prob: d.market_prob ?? (d.raw_payload?.yes_ask ? d.raw_payload.yes_ask / 100 : 0),
            edge_pct: d.edge_pct ?? d.raw_payload?.edge ?? 0
        })) || [];
        
        setEdges(normalized);
      } catch (err) {
        console.error("Error fetching kalshi_edges:", err);
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

  return { edges, loading };
};
