import { TrendingUp, TrendingDown, DollarSign, Wallet } from "lucide-react";
import { usePortfolioState } from "@/hooks/useSupabaseData";
import { forwardRef } from "react";

const formatCurrency = (val: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(val);

const PortfolioHero = forwardRef<HTMLDivElement, {}>((props, ref) => {
  const { portfolio, loading } = usePortfolioState();

  if (loading) {
    return (
      <div ref={ref} className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-card rounded-lg border border-border p-6 animate-pulse">
            <div className="h-4 bg-muted rounded w-24 mb-3" />
            <div className="h-8 bg-muted rounded w-32" />
          </div>
        ))}
      </div>
    );
  }

  const equity = portfolio?.total_equity ?? 0;
  const cash = portfolio?.available_cash ?? 0;
  const invested = equity - cash;
  const isPositive = equity >= 0;

  return (
    <div ref={ref} className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className={`bg-card rounded-lg border border-border p-6 ${isPositive ? "border-glow-profit" : "border-glow-loss"}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Total Equity</span>
          {isPositive ? (
            <TrendingUp className="w-5 h-5 text-profit" />
          ) : (
            <TrendingDown className="w-5 h-5 text-loss" />
          )}
        </div>
        <p className={`text-3xl font-bold font-mono ${isPositive ? "text-profit glow-profit" : "text-loss glow-loss"}`}>
          {formatCurrency(equity)}
        </p>
      </div>

      <div className="bg-card rounded-lg border border-border p-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Available Cash</span>
          <Wallet className="w-5 h-5 text-info" />
        </div>
        <p className="text-3xl font-bold font-mono text-foreground">
          {formatCurrency(cash)}
        </p>
      </div>

      <div className="bg-card rounded-lg border border-border p-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted-foreground font-medium uppercase tracking-wider">Invested</span>
          <DollarSign className="w-5 h-5 text-accent" />
        </div>
        <p className="text-3xl font-bold font-mono text-accent">
          {formatCurrency(invested)}
        </p>
      </div>
    </div>
  );
});

export default PortfolioHero;
