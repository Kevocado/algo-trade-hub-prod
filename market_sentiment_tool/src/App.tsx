import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
import { useState } from "react";
// Pages
import Home from "@/pages/Home";
import ShadowBacktester from "@/pages/ShadowBacktester";
import Models from "@/pages/Models";
import Scoreboard from "@/pages/Scoreboard";
import SportsEdges from "@/pages/SportsEdges";
import JobsNowcast from "@/pages/JobsNowcast";
import Cpi from "@/pages/Cpi";
import Journal from "@/pages/Journal";
import Health from "@/pages/Health";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { NoOrdersBanner } from "@/components/NoOrdersBanner";
import { usePortfolio } from "@/hooks/usePortfolio";
import { portfolioHeadline } from "@/lib/portfolioTruth";
import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen, HeartPulse, Menu, X } from "lucide-react";

const SidebarContent = () => {
  const { portfolio } = usePortfolio();
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
          <BookOpen className="w-5 h-5 text-emerald-400" /> Journal
        </NavLink>
        <NavLink
          to="/models"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Cpu className="w-5 h-5 text-indigo-400" /> Models
        </NavLink>
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
          <Briefcase className="w-5 h-5 text-sky-400" /> Jobs nowcast
        </NavLink>
        <NavLink
          to="/cpi"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <BarChart3 className="w-5 h-5 text-amber-400" /> CPI Display
        </NavLink>
        <NavLink
          to="/health"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <HeartPulse className="w-5 h-5 text-teal-400" /> Health
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
  const [mobileOpen, setMobileOpen] = useState(false);
  
  return (
    <>
      {mobileOpen ? (
        // Mobile view: sidebar overlay + close button + backdrop
        <>
          <button
            className="md:hidden fixed bottom-4 right-4 z-50 rounded-full bg-emerald-500 p-3 text-white shadow-lg hover:bg-emerald-600"
            onClick={() => setMobileOpen(false)}
            aria-label="Close menu"
          >
            <X className="w-6 h-6" />
          </button>
          <div className="fixed inset-y-0 left-0 z-50 w-64 bg-slate-950 text-slate-200 border-r border-slate-900 flex flex-col">
            <SidebarContent />
          </div>
          <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={() => setMobileOpen(false)} />
        </>
      ) : (
        // Desktop view: sidebar + mobile menu button
        <>
          <SidebarContent />
          <button
            className="md:hidden fixed bottom-4 right-4 z-50 rounded-full bg-emerald-500 p-3 text-white shadow-lg hover:bg-emerald-600"
            onClick={() => setMobileOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="w-6 h-6" />
          </button>
        </>
      )}
      
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        <NoOrdersBanner />
        {children}
      </main>
    </>
  );
};

function Guarded({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary resetKey={useLocation().pathname}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Guarded>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/lab" element={<Navigate to="/journal" replace />} />
          <Route path="/shadow" element={<ShadowBacktester />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/models" element={<Models />} />
          <Route path="/scoreboard" element={<Scoreboard />} />
          <Route path="/shadow-scoreboard" element={<Navigate to="/scoreboard" replace />} />
          <Route path="/sports" element={<SportsEdges />} />
          <Route path="/jobs" element={<JobsNowcast />} />
          <Route path="/cpi" element={<Cpi />} />
          <Route path="/health" element={<Health />} />
        </Routes>
        </Guarded>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;