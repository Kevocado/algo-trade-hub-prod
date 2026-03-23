import { TrendingUp } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";

const sampleData = [
  { day: "Mon", equity: 100000 },
  { day: "Tue", equity: 100450 },
  { day: "Wed", equity: 99800 },
  { day: "Thu", equity: 101200 },
  { day: "Fri", equity: 102100 },
  { day: "Sat", equity: 101800 },
  { day: "Sun", equity: 103500 },
];

export default function EquityCurve() {
  return (
    <div className="rounded-lg border border-border bg-card flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <TrendingUp className="w-4 h-4 text-profit" />
        <h3 className="text-sm font-semibold text-foreground uppercase tracking-wider">Equity Curve</h3>
        <span className="ml-auto text-[10px] font-mono text-muted-foreground">Live data coming soon</span>
      </div>
      <div className="flex-1 p-4 min-h-[250px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={sampleData}>
            <defs>
              <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(142, 72%, 50%)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="hsl(142, 72%, 50%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 14%, 18%)" />
            <XAxis dataKey="day" tick={{ fill: "hsl(215, 12%, 50%)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "hsl(215, 12%, 50%)", fontSize: 11 }} axisLine={false} tickLine={false} domain={["dataMin - 500", "dataMax + 500"]} />
            <Tooltip
              contentStyle={{ background: "hsl(220, 18%, 10%)", border: "1px solid hsl(220, 14%, 18%)", borderRadius: 8, color: "hsl(210, 20%, 90%)", fontSize: 12 }}
            />
            <Area type="monotone" dataKey="equity" stroke="hsl(142, 72%, 50%)" fill="url(#equityGradient)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
