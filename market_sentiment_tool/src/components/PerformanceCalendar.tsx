import { CalendarDays, Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTrades } from "@/hooks/useSupabaseData";
import { useMemo } from "react";

const now = new Date();
const year = now.getFullYear();
const month = now.getMonth();
const daysInMonth = new Date(year, month + 1, 0).getDate();
const firstDayOfWeek = new Date(year, month, 1).getDay();
const monthName = now.toLocaleString("en-US", { month: "long", year: "numeric" });
const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const formatCurrency = (val: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(val);

export default function PerformanceCalendar() {
  const { trades, loading } = useTrades();

  // Aggregate PnL by YYYY-MM-DD
  const dailyPnL = useMemo(() => {
    const aggs: Record<string, number> = {};
    trades.forEach((t) => {
      if (!t.timestamp || t.pnl == null) return;
      const dateStr = t.timestamp.split("T")[0];
      aggs[dateStr] = (aggs[dateStr] || 0) + Number(t.pnl);
    });
    return aggs;
  }, [trades]);

  const blanks = Array.from({ length: firstDayOfWeek }, (_, i) => i);
  const days = Array.from({ length: daysInMonth }, (_, i) => {
    const d = i + 1;
    // Construct local date without timezone shift issues
    const dateObj = new Date(year, month, d);
    // Pad month/day to match ISO format
    const m = String(month + 1).padStart(2, "0");
    const dayStr = String(d).padStart(2, "0");
    const dateStr = `${year}-${m}-${dayStr}`;

    return { day: d, dateStr, isFuture: dateObj > now };
  });

  return (
    <div className="rounded-lg border border-border bg-card flex flex-col h-full overflow-hidden shadow-lg animate-fade-in">
      <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-black/10">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-info/10">
            <CalendarDays className="w-5 h-5 text-info" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground tracking-wide uppercase flex items-center gap-2">
              Performance
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                </TooltipTrigger>
                <TooltipContent className="max-w-[250px] space-y-1">
                  <p className="font-semibold text-foreground">PnL Grid Matrix</p>
                  <p className="text-xs text-muted-foreground">Aggregated daily portfolio net profit/loss mapped to a calendar view. Allows quick tracking of absolute winning/losing session clusters.</p>
                </TooltipContent>
              </Tooltip>
            </h3>
            <span className="text-xs font-mono text-muted-foreground">{monthName}</span>
          </div>
        </div>
        {loading && (
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-info animate-pulse" />
            <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Syncing</span>
          </div>
        )}
      </div>

      <div className="flex-1 p-4">
        <div className="grid grid-cols-7 gap-2 mb-2">
          {weekdays.map((d) => (
            <div key={d} className="text-center text-[10px] font-mono font-bold tracking-widest text-muted-foreground/70 uppercase">
              {d}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-2">
          {blanks.map((b) => (
            <div key={`b-${b}`} className="aspect-square" />
          ))}
          {days.map(({ day, dateStr, isFuture }) => {
            const pnl = dailyPnL[dateStr];

            let bgClass = "bg-muted/10 border-transparent hover:border-border";
            let textClass = "text-muted-foreground/50";
            let valueClass = "";

            if (pnl !== undefined) {
              if (pnl > 0) {
                bgClass = "bg-profit/10 border-profit/20";
                textClass = "text-profit";
                valueClass = "text-profit glow-profit";
              } else if (pnl < 0) {
                bgClass = "bg-loss/10 border-loss/20";
                textClass = "text-loss";
                valueClass = "text-loss glow-loss";
              } else {
                bgClass = "bg-muted/20 border-border/50";
                textClass = "text-foreground";
                valueClass = "text-gray-400 text-xs font-extrabold";
              }
            } else if (isFuture) {
              bgClass = "bg-transparent border-dashed border-border/30";
              textClass = "text-muted-foreground/30";
            }

            return (
              <div
                key={day}
                className={`aspect-square rounded-md border flex flex-col items-center justify-center p-1 transition-all duration-300 ${bgClass}`}
              >
                <span className={`text-[10px] font-mono leading-none mb-1 ${textClass}`}>
                  {day}
                </span>
                {pnl !== undefined ? (
                  <span className={`font-mono leading-none ${valueClass}`}>
                    {pnl > 0 ? "+" : ""}{formatCurrency(pnl)}
                  </span>
                ) : !isFuture ? (
                  <span className="text-muted-foreground/40 text-xs font-mono font-medium">—</span>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
