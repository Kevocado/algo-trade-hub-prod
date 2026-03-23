import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { LayoutDashboard, CloudLightning, Trophy, Activity, Wallet } from "lucide-react";

// Pages
import Home from "./pages/Home";
import KalshiLab from "./pages/KalshiLab";
import SportsDesk from "./pages/SportsDesk";

const Sidebar = () => {
  return (
    <div className="w-64 bg-slate-900 text-slate-200 border-r border-slate-800 h-screen sticky top-0 flex flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/40">
            <Activity className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white">Algo Hub</span>
        </div>
      </div>
      
      <nav className="flex-1 px-4 space-y-2 mt-4">
        <NavLink 
          to="/" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-800 text-slate-400 hover:text-slate-200'}`}
        >
          <LayoutDashboard className="w-5 h-5" /> Portfolio
        </NavLink>
        <NavLink 
          to="/kalshi" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-800 text-slate-400 hover:text-slate-200'}`}
        >
          <CloudLightning className="w-5 h-5" /> Kalshi Lab
        </NavLink>
        <NavLink 
          to="/sports" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-800 text-slate-400 hover:text-slate-200'}`}
        >
          <Trophy className="w-5 h-5" /> Sports Desk
        </NavLink>
      </nav>

      <div className="p-4 border-t border-slate-800">
        <div className="bg-slate-950 rounded-xl p-4 border border-slate-800 shadow-sm">
          <div className="flex items-center gap-2 mb-2 text-slate-400 text-sm font-medium">
            <Wallet className="w-4 h-4" /> Live Balance
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">$24,192<span className="text-slate-500 text-sm">.50</span></div>
          <div className="text-xs text-emerald-400 flex items-center gap-1 mt-1 font-medium bg-emerald-500/10 w-fit px-2 py-0.5 rounded-full">
            +3.4% today
          </div>
        </div>
      </div>
    </div>
  );
};

const AppShell = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <main className="flex-1 min-h-screen overflow-auto bg-slate-50">
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
          <Route path="/kalshi" element={<KalshiLab />} />
          <Route path="/sports" element={<SportsDesk />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
