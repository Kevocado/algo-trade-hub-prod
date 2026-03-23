import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import type { Tables } from "@/integrations/supabase/types";

export function usePortfolioState() {
  const [portfolio, setPortfolio] = useState<Tables<"portfolio_state"> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from("portfolio_state")
        .select("*")
        .order("timestamp", { ascending: false })
        .limit(1)
        .single();
      if (data) setPortfolio(data);
      setLoading(false);
    };
    fetch();

    const channel = supabase
      .channel("portfolio_state_changes")
      .on("postgres_changes", { event: "*", schema: "public", table: "portfolio_state" }, (payload) => {
        if (payload.new) setPortfolio(payload.new as Tables<"portfolio_state">);
      })
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  return { portfolio, loading };
}

export function usePortfolioHistory() {
  const [history, setHistory] = useState<Tables<"portfolio_state">[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from("portfolio_state")
        .select("*")
        .order("timestamp", { ascending: false })
        .limit(100);
      if (data) setHistory(data.reverse()); // Reverse to get chronological order for charts
      setLoading(false);
    };
    fetch();

    const channel = supabase
      .channel("portfolio_history_changes")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "portfolio_state" }, (payload) => {
        setHistory((prev) => [...prev, payload.new as Tables<"portfolio_state">].slice(-100)); // maintain max 100 on the right
      })
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  return { history, loading };
}

export function useTrades() {
  const [trades, setTrades] = useState<Tables<"trades">[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from("trades")
        .select("*")
        .order("timestamp", { ascending: false })
        .limit(50);
      if (data) setTrades(data);
      setLoading(false);
    };
    fetch();

    const channel = supabase
      .channel("trades_changes")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "trades" }, (payload) => {
        setTrades((prev) => [payload.new as Tables<"trades">, ...prev].slice(0, 50));
      })
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  return { trades, loading };
}

export function useAgentLogs() {
  const [logs, setLogs] = useState<Tables<"agent_logs">[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<"connecting" | "connected" | "error">("connecting");

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from("agent_logs")
        .select("*")
        .order("timestamp", { ascending: false })
        .limit(100);
      if (data) setLogs(data);
      setLoading(false);
    };
    fetch();

    const channel = supabase
      .channel("agent_logs_changes")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "agent_logs" }, (payload) => {
        setStatus("connected");
        setLogs((prev) => [payload.new as Tables<"agent_logs">, ...prev].slice(0, 100));
      })
      .subscribe((subscribeStatus) => {
        if (subscribeStatus === "SUBSCRIBED") setStatus("connected");
        if (subscribeStatus === "CHANNEL_ERROR") setStatus("error");
        if (subscribeStatus === "TIMED_OUT") setStatus("error");
      });

    return () => { supabase.removeChannel(channel); };
  }, []);

  return { logs, loading, status };
}

export function useUserSettings() {
  const [settings, setSettings] = useState<Tables<"user_settings"> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      const { data } = await supabase
        .from("user_settings")
        .select("*")
        .limit(1)
        .single();
      if (data) setSettings(data);
      setLoading(false);
    };
    fetch();
  }, []);

  const toggleAutoTrade = async (enabled: boolean) => {
    // Optimistic update so the UI feels responsive
    setSettings((prev) => prev ? { ...prev, auto_trade_enabled: enabled } : {
      user_id: "preview",
      auto_trade_enabled: enabled,
      max_daily_drawdown: 0.05,
      updated_at: new Date().toISOString()
    });

    if (!settings?.user_id) return;

    try {
      const { data, error } = await supabase
        .from("user_settings")
        .update({ auto_trade_enabled: enabled, updated_at: new Date().toISOString() })
        .eq("user_id", settings.user_id)
        .select()
        .single();

      if (data) setSettings(data);
      if (error) console.warn("Supabase update failed (RLS likely):", error);
    } catch (e) {
      console.warn("Toggle warning:", e);
    }
  };

  return { settings, loading, toggleAutoTrade };
}
