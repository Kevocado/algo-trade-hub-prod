import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
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
import Weather from "@/pages/Weather";
import { NoOrdersBanner } from "@/components/NoOrdersBanner";
import { usePortfolio } from "@/hooks/usePortfolio";
import { portfolioHeadline } from "@/lib/portfolioTruth";
import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen, HeartPulse, Menu, X } from "lucide-react";

/**
 * The nav itself, written once and shared by the desktop rail and the phone overlay.
 *
 * `onNavigate` is the overlay's way of saying "the reader picked a page": the drawer closes, so a
 * new page is never read through it. The rail passes nothing, because the rail is always there.
 */
const SidebarBody = ({ onNavigate }: { onNavigate?: () => void }) => {
  const { portfolio } = usePortfolio();
  // The sidebar used to render "LIVE BALANCE $0.00" from an empty table, which reads as a flat
  // book. This product places no orders, so it says that instead of showing a number nobody can act
  // on -- and an unreadable payload reads as unknown, never as zero.
  const headline = portfolioHeadline(portfolio);

  return (
    <>
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/40">
            <Activity className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white uppercase italic">Algo Trade Hub</span>
        </div>
      </div>
      
      <nav onClick={onNavigate} className="flex-1 px-4 space-y-2 mt-4">
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
          <Briefcase className="w-5 h-5 text-sky-400" /> Jobs nowcast
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
        <NavLink
          to="/health"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          {/* Freshness of every timer and forecaster. Not a scoreboard: it answers "is anything
              running", which is a different question from "who is winning". */}
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
    </>
  );
};

/**
 * The rail: the sidebar as it has always been, from 768px up.
 *
 * Below that it is display:none, because on a 375px phone a 256px rail took two thirds of the
 * screen and left every page squeezed into what was left. `hidden md:flex` is the whole of that
 * decision: the breakpoint is CSS, so there is no width check in JavaScript to fall out of step
 * with the stylesheet, and at 768px and up this is byte-for-byte the sidebar it was.
 */
const SidebarRail = () => (
  <div
    data-testid="sidebar-rail"
    className="hidden md:flex flex-col w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0"
  >
    <SidebarBody />
  </div>
);

/**
 * The shell: the rail beside the page, and -- on a phone -- a menu button that opens the same nav
 * over the page.
 *
 * On a 375px screen the rail was two thirds of the viewport, so every page was cramped. Below
 * 768px the rail is hidden and the button opens the nav as an overlay instead; from 768px up
 * nothing changes at all, and the button is not even on the screen.
 *
 * The overlay closes on a route change (the reader asked for a page, not for a page behind a
 * drawer), on Escape and on a click on the backdrop. It is a real `<button>`, so it is reachable
 * by keyboard, and it carries `aria-expanded`, so a screen reader says whether the menu is open.
 */
export const AppShell = ({ children }: { children: React.ReactNode }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  // A route change closes the menu.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // Escape closes it, and hands the keyboard back to the button that opened it.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // The panel takes focus when it opens, so the next Tab lands on the first link inside it.
  useEffect(() => {
    if (menuOpen) overlayRef.current?.focus();
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    // Column on a phone (the menu bar sits above the page), row from 768px up (the rail sits
    // beside the page, as it always has).
    <div className="flex min-h-screen flex-col bg-slate-950 md:flex-row">
      <SidebarRail />
      {menuOpen && (
        <>
          <div
            data-testid="sidebar-backdrop"
            aria-hidden="true"
            onClick={closeMenu}
            className="md:hidden fixed inset-0 z-40 bg-slate-950/70"
          />
          <div
            id="site-menu"
            data-testid="sidebar-overlay"
            role="dialog"
            aria-label="Site menu"
            tabIndex={-1}
            ref={overlayRef}
            className="md:hidden fixed inset-y-0 left-0 z-50 flex flex-col w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen shadow-2xl"
          >
            <SidebarBody onNavigate={closeMenu} />
          </div>
        </>
      )}
      {/* The phone's way into the nav. md:hidden, so from 768px up the page starts at the top
          exactly as it always did. */}
      <div className="md:hidden sticky top-0 z-30 flex items-center gap-3 border-b border-slate-900 bg-slate-950/95 px-4 py-3">
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-800 text-slate-300 hover:bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          {menuOpen ? (
            <X className="w-5 h-5" aria-hidden="true" />
          ) : (
            <Menu className="w-5 h-5" aria-hidden="true" />
          )}
        </button>
        <span className="text-sm font-bold uppercase italic tracking-tight text-white">Algo Trade Hub</span>
      </div>
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        <NoOrdersBanner />
        {children}
      </main>
    </div>
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
          <Route path="/jobs" element={<JobsNowcast />} />
          <Route path="/cpi" element={<Cpi />} />
          <Route path="/health" element={<Health />} />
          <Route path="/weather" element={<Weather />} />
        </Routes>
        </Guarded>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
