import { useState } from "react";
import { useFetch, api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";
import AddStockModal from "./AddStockModal";
import ClosePositionModal from "./ClosePositionModal";

const STATUS_BADGE = { WATCH:"badge-blue", BUY:"badge-green", CAUTION:"badge-yellow", EXIT:"badge-red", HOLD:"badge-muted", CLOSED:"badge-muted" };
const CONF_BADGE   = { high:"badge-green", medium:"badge-yellow", low:"badge-muted" };

function ProgressBar({ entry, current, sl, target }) {
  if (!current || !entry || !sl || !target || sl >= entry || target <= entry) return null;
  const range = target - sl;
  const pos   = Math.max(0, Math.min(100, ((current - sl) / range) * 100));
  const entryPos = Math.max(0, Math.min(100, ((entry - sl) / range) * 100));
  const color = current >= entry ? "var(--green)" : "var(--red)";
  return (
    <div className="progress-wrap">
      <div className="progress-fill" style={{ width: `${pos}%`, background: color }} />
      <div className="progress-marker" style={{ left: `${entryPos}%` }} />
    </div>
  );
}

function ScoreBar({ score }) {
  if (!score) return <span className="neu">—</span>;
  const color = score >= 70 ? "var(--green)" : score >= 55 ? "var(--yellow)" : "var(--red)";
  return (
    <div className="score-bar">
      <span style={{ color, fontWeight: 600, minWidth: 32 }}>{score.toFixed(0)}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${score}%`, background: color }} />
      </div>
    </div>
  );
}

export default function Watchlist() {
  const { data, loading, refetch } = useFetch("/watchlist");
  const [showAdd, setShowAdd]       = useState(false);
  const [closeStock, setCloseStock] = useState(null);
  const [filter, setFilter]         = useState("active");
  const [monitoring, setMonitoring] = useState(false);
  const toast = useToast();

  const items = data || [];
  const active = items.filter(w => !["CLOSED","EXIT"].includes(w.status));
  const filtered = filter === "active" ? active
    : filter === "closed" ? items.filter(w => ["CLOSED","EXIT"].includes(w.status))
    : items;

  // Summary stats
  const totalPnl = active.filter(w => w.pnl_percent != null).reduce((s, w) => s + w.pnl_percent, 0);
  const winners  = active.filter(w => w.pnl_percent > 0).length;
  const losers   = active.filter(w => w.pnl_percent < 0).length;

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
      {/* Stats row */}
      <div className="stats-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px,1fr))" }}>
        <div className="stat stat-blue">
          <div className="stat-label">Active Positions</div>
          <div className="stat-value">{active.length}</div>
          <div className="stat-sub">{winners}W / {losers}L</div>
        </div>
        <div className={`stat ${totalPnl >= 0 ? "stat-green" : "stat-red"}`}>
          <div className="stat-label">Open PnL</div>
          <div className="stat-value" style={{ color: totalPnl >= 0 ? "var(--green)" : "var(--red)" }}>
            {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(1)}%
          </div>
          <div className="stat-sub">across all positions</div>
        </div>
        <div className="stat stat-yellow">
          <div className="stat-label">Caution</div>
          <div className="stat-value">{active.filter(w => w.status === "CAUTION").length}</div>
          <div className="stat-sub">need attention</div>
        </div>
        <div className="stat stat-purple">
          <div className="stat-label">Avg Score</div>
          <div className="stat-value">
            {active.filter(w => w.entry_score).length
              ? (active.filter(w => w.entry_score).reduce((s,w) => s + w.entry_score, 0) / active.filter(w => w.entry_score).length).toFixed(0)
              : "—"}
          </div>
          <div className="stat-sub">entry quality</div>
        </div>
      </div>

      {/* Header */}
      <div className="section-header">
        <div>
          <div className="section-title">Watchlist</div>
          <div className="section-sub">{active.length} active · {items.filter(w => ["CLOSED","EXIT"].includes(w.status)).length} closed</div>
        </div>
        <div className="section-actions">
          <button className="btn" onClick={runMonitor} disabled={monitoring}>
            {monitoring ? <span className="spin" /> : "↻"} Run Monitor
          </button>
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ Add Stock</button>
        </div>
      </div>

      {/* Filter pills */}
      <div className="pills">
        {["active","closed","all"].map(f => (
          <button key={f} className={`pill ${filter===f?"active":""}`} onClick={() => setFilter(f)}>
            {f.charAt(0).toUpperCase()+f.slice(1)}
            {f==="active" && ` (${active.length})`}
          </button>
        ))}
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div className="empty"><div className="empty-icon">📋</div><div className="empty-text">No stocks here. Add one to get started.</div></div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="right">Live Price</th>
                  <th className="right">Entry</th>
                  <th className="right">Stop Loss</th>
                  <th className="right">Target</th>
                  <th className="right">PnL</th>
                  <th>Progress</th>
                  <th>Score</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(w => {
                  const pnl = w.pnl_percent;
                  const isActive = !["CLOSED","EXIT"].includes(w.status);
                  return (
                    <tr key={w.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{w.symbol}</div>
                        {w.company_name && <div style={{ fontSize: 11, color: "var(--muted)" }}>{w.company_name}</div>}
                      </td>
                      <td className="right" style={{ fontVariantNumeric: "tabular-nums" }}>
                        {w.live_price ? <strong>₹{w.live_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong> : <span className="neu">—</span>}
                      </td>
                      <td className="right" style={{ color: "var(--text2)", fontVariantNumeric: "tabular-nums" }}>₹{w.entry_price?.toFixed(2)}</td>
                      <td className="right neg" style={{ fontVariantNumeric: "tabular-nums" }}>₹{w.stop_loss?.toFixed(2)}</td>
                      <td className="right pos" style={{ fontVariantNumeric: "tabular-nums" }}>₹{w.target?.toFixed(2)}</td>
                      <td className="right">
                        {pnl != null
                          ? <span className={pnl >= 0 ? "pos" : "neg"}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%</span>
                          : <span className="neu">—</span>}
                      </td>
                      <td>
                        <ProgressBar entry={w.entry_price} current={w.live_price} sl={w.stop_loss} target={w.target} />
                      </td>
                      <td><ScoreBar score={w.entry_score} /></td>
                      <td>
                        {w.confidence
                          ? <span className={`badge ${CONF_BADGE[w.confidence]||"badge-muted"}`}>{w.confidence}</span>
                          : <span className="neu">—</span>}
                      </td>
                      <td><span className={`badge ${STATUS_BADGE[w.status]||"badge-muted"}`}>{w.status}</span></td>
                      <td style={{ color: "var(--muted)", fontSize: 12 }}>{w.added_at?.slice(0,10)}</td>
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
