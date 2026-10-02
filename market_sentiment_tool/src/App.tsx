import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
// Pages
import Home from "@/pages/Home";
import ShadowBacktester from "@/pages/ShadowBacktester";
import Models from "@/pages/Models";
import Scoreboard from "@/pages/Scoreboard";
import SportsEdges from "@/pages/SportsEdges";
import JobsScorecard from "@/pages/JobsScorecard";
import Cpi from "@/pages/Cpi";
import Journal from "@/pages/Journal";
import { NoOrdersBanner } from "@/components/NoOrdersBanner";
import { usePortfolio } from "@/hooks/usePortfolio";
import { portfolioHeadline } from "@/lib/portfolioTruth";
import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen } from "lucide-react";

const Sidebar = () => {
  const { portfolio } = usePortfolio();
  // The sidebar used to render "LIVE BALANCE $0.00" from an empty table, which reads as a flat
  // book. This product places no orders, so it says that instead of showing a number nobody can act
  // on -- and an unreadable payload reads as unknown, never as zero.
  const headline = portfolioHeadline(portfolio);
  
  return (
    <div className="w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0 flex flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/40">
            <Activity className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white uppercase italic">Algo Trade Hub</span>
        </div>
      </div>
      
      <nav className="flex-1 px-4 space-y-2 mt-4">
        <NavLink 
          to="/" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <LayoutDashboard className="w-5 h-5" /> Portfolio
        </NavLink>
        {/* "Crypto Shadow", not "Shadow". This is the nav entry that cost the owner a page on
            2026-09-28: a list item reading "Shadow" beside one reading "Scoreboard" reads as two
            halves of the same thing, and they are not. This page is the crypto shadow-timeline
            backtester; the other is every engine's Brier against the market. Naming the domain
            here is the whole fix -- the word "shadow" on its own in a nav list is the collision,
            and the route below is /shadow, so the label and the path finally say the same thing. */}
        <NavLink
          to="/shadow"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <LineChart className="w-5 h-5 text-amber-400" /> Crypto Shadow
        </NavLink>
        <NavLink
          to="/journal"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          {/* The flagship (v2 spec §11): every forecaster's frozen, settled, scored record. */}
          <BookOpen className="w-5 h-5 text-emerald-400" /> Journal
        </NavLink>
        <NavLink
          to="/models"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          {/* "Models", not "Engines": the product's own word for these is engine, and that word
              appears in every row of the page, but the person reading the nav asked what the MODELS
              are doing and did not know the site had any. It sits above Scoreboard in the list
              because it is the frame the other pages sit inside. */}
          <Cpu className="w-5 h-5 text-indigo-400" /> Models
        </NavLink>
        {/* "Engine Scoreboard", not "Shadow Scoreboard" and not "Shadow". The h1 has always said
            "Engine scoreboard" and the page scores ENGINES against their markets, so the nav says
            what is being scored. "Shadow" would name a word this product uses for two other
            things (the crypto timeline at /shadow, and the not-promoted gate status), and a nav
            entry that reads like a sibling of /shadow is what sent the owner to the wrong page on
            2026-09-28. People who type "shadow scoreboard" still land here, via the redirect
            below -- the name works without being the name. */}
        <NavLink
          to="/scoreboard"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Scale className="w-5 h-5 text-rose-400" /> Engine Scoreboard
        </NavLink>
        <NavLink
          to="/sports"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Trophy className="w-5 h-5 text-cyan-400" /> Sports
        </NavLink>
        <NavLink
          to="/jobs"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Briefcase className="w-5 h-5 text-sky-400" /> Jobs Scorecard
        </NavLink>
        {/* Label says "Display", not "Nowcast" or "Edges". This board is NOT a board of
            opportunities, and a nav entry that reads like the other four would put the claim back
            that the page spends its length taking away. */}
        <NavLink
          to="/cpi"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <BarChart3 className="w-5 h-5 text-amber-400" /> CPI Display
        </NavLink>
      </nav>

      <div className="p-4 border-t border-slate-900">
        <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800 shadow-sm">
          <div className="flex items-center gap-2 mb-2 text-slate-400 text-sm font-medium uppercase tracking-tighter">
            <Wallet className="w-4 h-4" aria-hidden="true" /> {headline.label}
          </div>
          <div
            className={`text-2xl font-bold tracking-tight ${
              headline.tone === "muted" ? "text-slate-400" : "text-white"
            }`}
          >
            {headline.value}
          </div>
          <div className="text-[10px] text-emerald-400 flex items-center gap-1 mt-1 font-black bg-emerald-500/10 w-fit px-2 py-0.5 rounded-full border border-emerald-500/20 uppercase">
             Live Telemetry
          </div>
        </div>
      </div>
    </div>
  );
};

const AppShell = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex min-h-screen bg-slate-950">
      <Sidebar />
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        <NoOrdersBanner />
        {children}
      </main>
    </div>
  );
};

function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Home />} />
          {/* /lab was the Prediction Lab; the journal replaced it (v2 spec §9). A redirect, not a 404, so
              bookmarks and links keep working. */}
          <Route path="/lab" element={<Navigate to="/journal" replace />} />
          {/* The crypto shadow-timeline backtester, which keeps the /shadow route it has always
              had. It is NOT the scoreboard and never becomes it: a redirect from here to the
              scoreboard would swap a crypto backtester for an engine scoreboard without saying so,
              which is the same collision wearing a hat. The page says what it is and links to the
              scoreboard instead. */}
          <Route path="/shadow" element={<ShadowBacktester />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/models" element={<Models />} />
          {/* The engine scoreboard, canonically at /scoreboard.
              `/engines` was the other candidate and was rejected: /models already lists every
              engine one row at a time, so /engines would have been a SECOND route that means "the
              engines", differing only in depth. That is the same collision this branch exists to
              close, one level down. `/scoreboard` names the artifact rather than its contents, so
              it takes a new engine without the name going stale, and it already matches the
              endpoint (/api/scoreboard) and the file (Scoreboard.tsx), so it costs no rename. */}
          <Route path="/scoreboard" element={<Scoreboard />} />
          {/* `/shadow-scoreboard` -> `/scoreboard`, permanently.
              The owner's approval for this page was literally called "the shadow scoreboard", so
              that string is a name people will type. A redirect makes the NAME work without making
              it the NAME, which is the whole distinction: "shadow" already means two things in
              this product -- the crypto timeline and the not-promoted gate status -- and the engine
              scoreboard is about neither. An earlier revision of this branch made
              /shadow-scoreboard canonical, which left the ambiguity in a route instead of a nav
              label, where it is expensive to change. It is a redirect here and nothing else.
              Same component, same /api/scoreboard read, address bar updated to the real path. */}
          <Route path="/shadow-scoreboard" element={<Navigate to="/scoreboard" replace />} />
          <Route path="/sports" element={<SportsEdges />} />
          <Route path="/jobs" element={<JobsScorecard />} />
          <Route path="/cpi" element={<Cpi />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
