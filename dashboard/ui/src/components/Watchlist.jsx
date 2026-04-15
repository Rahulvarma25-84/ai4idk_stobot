import { useState } from "react";
import { useFetch, api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";
import AddStockModal from "./AddStockModal";
import ClosePositionModal from "./ClosePositionModal";

const STATE_BADGE  = { STRONG:"badge-green", NEUTRAL:"badge-blue", WEAK:"badge-red" };
const ACTION_STYLE = { HOLD:"pos", MONITOR:"neu", CAUTION:"text-yellow", EXIT:"neg" };
const STATUS_BADGE = { WATCH:"badge-blue", BUY:"badge-green", CAUTION:"badge-yellow", EXIT:"badge-red", HOLD:"badge-muted", CLOSED:"badge-muted" };

function ProgressBar({ entry, current, sl, target }) {
  if (!current || !entry || !sl || !target || sl >= entry || target <= entry) return null;
  const range = target - sl;
  const pos   = Math.max(0, Math.min(100, ((current - sl) / range) * 100));
  const ep    = Math.max(0, Math.min(100, ((entry  - sl) / range) * 100));
  const color = current >= entry ? "var(--green)" : "var(--red)";
  return (
    <div className="progress-wrap">
      <div className="progress-fill" style={{ width:`${pos}%`, background:color }} />
      <div className="progress-marker" style={{ left:`${ep}%` }} />
    </div>
  );
}

function ScoreCell({ value, thresholds = [70, 50] }) {
  if (value == null) return <span className="neu">—</span>;
  const color = value >= thresholds[0] ? "var(--green)" : value >= thresholds[1] ? "var(--yellow)" : "var(--red)";
  return <span style={{ color, fontWeight:600 }}>{value.toFixed(0)}</span>;
}

export default function Watchlist() {
  const { data, loading, refetch } = useFetch("/watchlist");
  const [showAdd, setShowAdd]       = useState(false);
  const [closeStock, setCloseStock] = useState(null);
  const [filter, setFilter]         = useState("active");
  const [monitoring, setMonitoring] = useState(false);
  const toast = useToast();

  const items  = data || [];
  const active = items.filter(w => !["CLOSED","EXIT"].includes(w.status));
  const filtered = filter === "active" ? active
    : filter === "closed" ? items.filter(w => ["CLOSED","EXIT"].includes(w.status))
    : items;

  const strong  = active.filter(w => w.trade_state === "STRONG").length;
  const neutral = active.filter(w => w.trade_state === "NEUTRAL").length;
  const weak    = active.filter(w => w.trade_state === "WEAK").length;
  const openPnl = active.filter(w => w.pnl_percent != null).reduce((s,w) => s + w.pnl_percent, 0);

  async function changeStatus(symbol, status) {
    await api.patch(`/watchlist/${symbol}/status`, { status });
    toast(`${symbol} → ${status}`, "info");
    refetch();
  }

  async function deleteStock(symbol) {
    if (!confirm(`Remove ${symbol}?`)) return;
    await api.delete(`/watchlist/${symbol}`);
    toast(`${symbol} removed`, "info");
    refetch();
  }

  async function runMonitor() {
    setMonitoring(true);
    try {
      const results = await api.post("/monitor", {});
      toast(`Monitor done — ${results.length} positions checked`, "success");
      refetch();
    } catch { toast("Monitor failed", "error"); }
    finally { setMonitoring(false); }
  }

  if (loading) return <div style={{ display:"flex", justifyContent:"center", padding:80 }}><span className="spin" style={{ width:32, height:32, borderWidth:3 }} /></div>;

  return (
    <div>
      {/* Stats */}
      <div className="stats-grid">
        <div className="stat stat-blue">
          <div className="stat-label">Active Positions</div>
          <div className="stat-value">{active.length}</div>
          <div className="stat-sub">max 2 recommended</div>
        </div>
        <div className="stat stat-green">
          <div className="stat-label">Strong</div>
          <div className="stat-value" style={{ color:"var(--green)" }}>{strong}</div>
          <div className="stat-sub">exit score &lt; 30</div>
        </div>
        <div className="stat stat-yellow">
          <div className="stat-label">Neutral</div>
          <div className="stat-value" style={{ color:"var(--yellow)" }}>{neutral}</div>
          <div className="stat-sub">monitor only</div>
        </div>
        <div className="stat stat-red">
          <div className="stat-label">Weak</div>
          <div className="stat-value" style={{ color:"var(--red)" }}>{weak}</div>
          <div className="stat-sub">action needed</div>
        </div>
        <div className={`stat ${openPnl >= 0 ? "stat-green" : "stat-red"}`}>
          <div className="stat-label">Open PnL</div>
          <div className="stat-value" style={{ color: openPnl >= 0 ? "var(--green)" : "var(--red)" }}>
            {openPnl >= 0 ? "+" : ""}{openPnl.toFixed(1)}%
          </div>
          <div className="stat-sub">unrealised</div>
        </div>
      </div>

      {/* Header */}
      <div className="section-header">
        <div>
          <div className="section-title">Watchlist</div>
          <div className="section-sub">Trade state updates automatically on each monitor run</div>
        </div>
        <div className="section-actions">
          <button className="btn" onClick={runMonitor} disabled={monitoring}>
            {monitoring ? <span className="spin" /> : "↻"} Run Monitor
          </button>
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Stock</button>
        </div>
      </div>

      <div className="pills">
        {["active","closed","all"].map(f => (
          <button key={f} className={`pill ${filter===f?"active":""}`} onClick={() => setFilter(f)}>
            {f.charAt(0).toUpperCase()+f.slice(1)}{f==="active"?` (${active.length})`:""}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty"><div className="empty-icon">📋</div><div className="empty-text">No stocks. Add one to get started.</div></div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="right">Live</th>
                  <th className="right">Entry</th>
                  <th className="right">SL</th>
                  <th className="right">Target</th>
                  <th className="right">PnL</th>
                  <th>Progress</th>
                  <th className="right">Entry</th>
                  <th className="right">Exit</th>
                  <th className="right">Opp</th>
                  <th>State</th>
                  <th>Action</th>
                  <th>Status</th>
                  <th>Controls</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(w => {
                  const isActive = !["CLOSED","EXIT"].includes(w.status);
                  const pnl = w.pnl_percent;
                  return (
                    <tr key={w.id}>
                      <td>
                        <div style={{ fontWeight:600 }}>{w.symbol}</div>
                        {w.company_name && <div style={{ fontSize:11, color:"var(--muted)" }}>{w.company_name}</div>}
                      </td>
                      <td className="right" style={{ fontVariantNumeric:"tabular-nums" }}>
                        {w.live_price ? <strong>₹{w.live_price.toLocaleString("en-IN",{minimumFractionDigits:2})}</strong> : <span className="neu">—</span>}
                      </td>
                      <td className="right" style={{ color:"var(--text2)", fontVariantNumeric:"tabular-nums" }}>₹{w.entry_price?.toFixed(2)}</td>
                      <td className="right neg" style={{ fontVariantNumeric:"tabular-nums" }}>₹{w.stop_loss?.toFixed(2)}</td>
                      <td className="right pos" style={{ fontVariantNumeric:"tabular-nums" }}>₹{w.target?.toFixed(2)}</td>
                      <td className="right">
                        {pnl != null ? <span className={pnl>=0?"pos":"neg"}>{pnl>=0?"+":""}{pnl.toFixed(2)}%</span> : <span className="neu">—</span>}
                      </td>
                      <td><ProgressBar entry={w.entry_price} current={w.live_price} sl={w.stop_loss} target={w.target} /></td>
                      <td className="right"><ScoreCell value={w.entry_score} /></td>
                      <td className="right"><ScoreCell value={w.exit_score} thresholds={[70, 40]} /></td>
                      <td className="right"><ScoreCell value={w.opportunity_score} /></td>
                      <td>
                        {w.trade_state
                          ? <span className={`badge ${STATE_BADGE[w.trade_state]||"badge-muted"}`}>{w.trade_state}</span>
                          : <span className="neu">—</span>}
                      </td>
                      <td>
                        <span className={ACTION_STYLE[w.suggested_action] || "neu"} style={{ fontWeight:600, fontSize:12 }}>
                          {w.suggested_action || "—"}
                        </span>
                      </td>
                      <td><span className={`badge ${STATUS_BADGE[w.status]||"badge-muted"}`}>{w.status}</span></td>
                      <td>
                        <div style={{ display:"flex", gap:4 }}>
                          {isActive && (
                            <>
                              <button className="btn btn-sm btn-red" onClick={() => setCloseStock(w)}>Close</button>
                              <select className="input" style={{ width:"auto", padding:"4px 6px", fontSize:11 }}
                                value={w.status} onChange={e => changeStatus(w.symbol, e.target.value)}>
                                <option value="WATCH">WATCH</option>
                                <option value="BUY">BUY</option>
                                <option value="CAUTION">CAUTION</option>
                                <option value="EXIT">EXIT</option>
                              </select>
                            </>
                          )}
                          <button className="btn btn-sm" onClick={() => deleteStock(w.symbol)} title="Remove">🗑</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAdd    && <AddStockModal onClose={() => setShowAdd(false)} onAdded={refetch} />}
      {closeStock && <ClosePositionModal stock={closeStock} onClose={() => setCloseStock(null)} onClosed={refetch} />}
    </div>
  );
}
