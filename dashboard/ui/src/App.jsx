import { useState, useEffect } from "react";
import { ToastProvider } from "./hooks/useToast";
import MarketBanner from "./components/MarketBanner";
import Watchlist from "./components/Watchlist";
import ScanResults from "./components/ScanResults";
import Performance from "./components/Performance";

const TABS = [
  { id:"watchlist",   icon:"📋", label:"Watchlist" },
  { id:"scans",       icon:"🔍", label:"Scan Results" },
  { id:"performance", icon:"📊", label:"Performance" },
];

function Clock() {
  const [t, setT] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setT(new Date()), 1000); return () => clearInterval(id); }, []);
  return (
    <span className="topbar-time">
      {t.toLocaleDateString("en-IN", { weekday:"short", day:"numeric", month:"short" })}
      &nbsp;·&nbsp;
      {t.toLocaleTimeString("en-IN", { hour:"2-digit", minute:"2-digit", second:"2-digit" })}
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState("watchlist");
  return (
    <ToastProvider>
      <div className="app">
        <header className="topbar">
          <div className="topbar-brand">
            <span className="topbar-brand-icon">⚡</span>
            <span className="topbar-brand-name">BuzzFlow</span>
            <span className="topbar-brand-tag">LIVE</span>
          </div>
          <nav className="topbar-nav">
            {TABS.map(t => (
              <button key={t.id} className={`topbar-nav-btn ${tab===t.id?"active":""}`} onClick={() => setTab(t.id)}>
                <span>{t.icon}</span> {t.label}
              </button>
            ))}
          </nav>
          <div className="topbar-right"><Clock /></div>
        </header>

        <main className="main">
          <MarketBanner />
          {tab === "watchlist"    && <Watchlist />}
          {tab === "scans"        && <ScanResults />}
          {tab === "performance"  && <Performance />}
        </main>

        <footer style={{ textAlign:"center", padding:"14px", color:"var(--muted)", fontSize:12, borderTop:"1px solid var(--border)" }}>
          BuzzFlow — For educational purposes only. Not financial advice.
        </footer>
      </div>
    </ToastProvider>
  );
}
