import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export interface KalshiPortfolioData {
  id: string;
  balance: number;
  portfolio_value: number;
  total_invested: number;
  total_pnl: number;
  wins: number;
  losses: number;
  open_positions: any[];
  updated_at: string;
}

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<KalshiPortfolioData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchPortfolio() {
      const { data, error } = await supabase
        .from("kalshi_portfolio")
        .select("*")
        .eq("id", "MAIN_ACCOUNT")
        .single();

      if (error) {
        console.error("Error fetching portfolio:", error);
      } else {
        setPortfolio(data);
      }
      setLoading(false);
    }

    fetchPortfolio();

    // Subscribe to real-time updates
    const channel = supabase
      .channel("kalshi_portfolio_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "kalshi_portfolio" },
        (payload) => {
          if (payload.new && (payload.new as KalshiPortfolioData).id === "MAIN_ACCOUNT") {
            setPortfolio(payload.new as KalshiPortfolioData);
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return { portfolio, loading };
}

export interface PortfolioMetrics {
  id: number;
  total_value: number;
  daily_pnl: number;
  cash_balance: number;
  updated_at: string;
}

export function usePortfolioMetrics() {
  const [metrics, setMetrics] = useState<PortfolioMetrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchMetrics() {
      const { data, error } = await supabase
        .from("portfolio_metrics")
        .select("*")
        .eq("id", 1)
        .single();

      if (error) {
        console.error("Error fetching portfolio metrics:", error);
      } else {
        setMetrics(data);
      }
      setLoading(false);
    }

    fetchMetrics();

    const channel = supabase
      .channel("portfolio_metrics_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "portfolio_metrics" },
        (payload) => {
          if (payload.new && (payload.new as PortfolioMetrics).id === 1) {
            setMetrics(payload.new as PortfolioMetrics);
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return { metrics, loading };
}
