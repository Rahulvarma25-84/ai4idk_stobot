import { useState } from "react";
import { useFetch, api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";

const SIG = { STRONG_BUY:"badge-green", BUY:"badge-green", WATCH:"badge-blue", SKIP:"badge-muted" };
const CONF = { high:"badge-green", medium:"badge-yellow", low:"badge-muted" };

export default function ScanResults() {
  const { data, loading, refetch } = useFetch("/scans?limit=200");
  const [adding, setAdding] = useState(null);
  const [sigFilter, setSigFilter] = useState("all");
  const [expanded, setExpanded] = useState(null);
  const toast = useToast();

  async function addToWatchlist(scan) {
    setAdding(scan.id);
    try {
      await api.post("/watchlist", {
        symbol: scan.symbol, entry_price: scan.entry_price,
        stop_loss: scan.stop_loss, target: scan.target,
        entry_score: scan.entry_score, confidence: scan.confidence,
        entry_zone_low: scan.entry_zone_low, entry_zone_high: scan.entry_zone_high,
        breakout_level: scan.breakout_level, pullback_level: scan.pullback_level,
        opportunity_score: scan.opportunity_score,
      });
      toast(`${scan.symbol} added to watchlist`, "success");
    } catch { toast("Failed to add", "error"); }
    finally { setAdding(null); }
  }

  if (loading) return <div style={{ display:"flex", justifyContent:"center", padding:80 }}><span className="spin" style={{ width:32, height:32, borderWidth:3 }} /></div>;

  const scans = data || [];
  const filtered = sigFilter === "all" ? scans : scans.filter(s => s.recommendation === sigFilter);

  return (
    <div>
      <div className="stats-grid">
        <div className="stat stat-blue"><div className="stat-label">Total Signals</div><div className="stat-value">{scans.length}</div></div>
        <div className="stat stat-green"><div className="stat-label">Strong Buy</div><div className="stat-value" style={{ color:"var(--green)" }}>{scans.filter(s=>s.recommendation==="STRONG_BUY").length}</div><div className="stat-sub">score ≥ 70</div></div>
        <div className="stat stat-yellow"><div className="stat-label">Buy</div><div className="stat-value" style={{ color:"var(--yellow)" }}>{scans.filter(s=>s.recommendation==="BUY").length}</div><div className="stat-sub">score 65–70</div></div>
        <div className="stat stat-purple"><div className="stat-label">Avg Opp Score</div>
          <div className="stat-value">{scans.length ? (scans.reduce((s,x)=>s+(x.opportunity_score||0),0)/scans.length).toFixed(0) : "—"}</div>
        </div>
      </div>

      <div className="section-header">
        <div>
          <div className="section-title">Scan Results</div>
          <div className="section-sub">Entry zones shown — you decide when to enter based on conditions</div>
        </div>
        <button className="btn" onClick={refetch}>↻ Refresh</button>
      </div>

      <div className="pills">
        {["all","STRONG_BUY","BUY","WATCH"].map(f => (
          <button key={f} className={`pill ${sigFilter===f?"active":""}`} onClick={() => setSigFilter(f)}>
            {f==="all" ? `All (${scans.length})` : `${f} (${scans.filter(s=>s.recommendation===f).length})`}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty"><div className="empty-icon">🔍</div><div className="empty-text">No scan results. Run the morning scan.</div></div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="right">Score</th>
                  <th className="right">Opp</th>
                  <th>Signal</th>
                  <th>Conf</th>
                  <th className="right">Entry Zone</th>
                  <th className="right">Breakout</th>
                  <th className="right">Pullback</th>
                  <th className="right">SL</th>
                  <th className="right">Target</th>
                  <th className="right">R:R</th>
                  <th className="right">RSI</th>
                  <th className="right">Vol</th>
                  <th className="right">Deliv%</th>
                  <th>Scanned</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(s => {
                  const rr = s.entry_price && s.stop_loss && s.target && s.entry_price > s.stop_loss
                    ? ((s.target - s.entry_price) / (s.entry_price - s.stop_loss)).toFixed(1) : "—";
                  const isExpanded = expanded === s.id;
                  return [
                    <tr key={s.id} style={{ cursor:"pointer" }} onClick={() => setExpanded(isExpanded ? null : s.id)}>
                      <td><span style={{ fontWeight:600 }}>{s.symbol}</span></td>
                      <td className="right">
                        <span style={{ fontWeight:700, color: s.entry_score>=70?"var(--green)":s.entry_score>=65?"var(--yellow)":"var(--red)" }}>
                          {s.entry_score?.toFixed(1)}
                        </span>
                      </td>
                      <td className="right" style={{ color:"var(--purple)", fontWeight:600 }}>{s.opportunity_score?.toFixed(0)||"—"}</td>
                      <td><span className={`badge ${SIG[s.recommendation]||"badge-muted"}`}>{s.recommendation}</span></td>
                      <td><span className={`badge ${CONF[s.confidence]||"badge-muted"}`}>{s.confidence}</span></td>
                      <td className="right" style={{ fontVariantNumeric:"tabular-nums", color:"var(--blue)" }}>
                        {s.entry_zone_low && s.entry_zone_high ? `₹${s.entry_zone_low?.toFixed(0)}–${s.entry_zone_high?.toFixed(0)}` : "—"}
                      </td>
                      <td className="right" style={{ fontVariantNumeric:"tabular-nums", color:"var(--green)" }}>
                        {s.breakout_level ? `₹${s.breakout_level?.toFixed(0)}` : "—"}
                      </td>
                      <td className="right" style={{ fontVariantNumeric:"tabular-nums", color:"var(--yellow)" }}>
                        {s.pullback_level ? `₹${s.pullback_level?.toFixed(0)}` : "—"}
                      </td>
                      <td className="right neg" style={{ fontVariantNumeric:"tabular-nums" }}>₹{s.stop_loss?.toFixed(2)}</td>
                      <td className="right pos" style={{ fontVariantNumeric:"tabular-nums" }}>₹{s.target?.toFixed(2)}</td>
                      <td className="right">
                        <span style={{ color:+rr>=2?"var(--green)":+rr>=1.5?"var(--yellow)":"var(--red)", fontWeight:600 }}>{rr}</span>
                      </td>
                      <td className="right" style={{ color: s.rsi>70?"var(--red)":s.rsi<40?"var(--yellow)":"var(--text2)" }}>{s.rsi?.toFixed(0)||"—"}</td>
                      <td className="right" style={{ color: s.volume_ratio>=1.2?"var(--green)":"var(--text2)" }}>{s.volume_ratio?.toFixed(2)||"—"}×</td>
                      <td className="right" style={{ color: s.delivery_score>=70?"var(--green)":s.delivery_score>=50?"var(--text2)":"var(--red)", fontWeight:600 }}>
                        {s.delivery_score != null ? `${s.delivery_score.toFixed(0)}` : "—"}
                      </td>
                      <td style={{ color:"var(--muted)", fontSize:12 }}>{s.scanned_at?.slice(0,16).replace("T"," ")}</td>
                      <td>
                        {["STRONG_BUY","BUY"].includes(s.recommendation) && (
                          <button className="btn btn-sm btn-green" disabled={adding===s.id} onClick={e => { e.stopPropagation(); addToWatchlist(s); }}>
                            {adding===s.id ? <span className="spin" /> : "+ Watch"}
                          </button>
                        )}
                      </td>
                    </tr>,
                    isExpanded && (
                      <tr key={`${s.id}-detail`}>
                        <td colSpan={15} style={{ background:"var(--bg2)", padding:"14px 20px" }}>
                          <div style={{ fontSize:13, color:"var(--text2)", lineHeight:1.7 }}>
                            <strong style={{ color:"var(--text)" }}>Entry Conditions:</strong><br />
                            🔵 Enter between ₹{s.entry_zone_low?.toFixed(0)}–₹{s.entry_zone_high?.toFixed(0)} on volume confirmation<br />
                            🟢 Breakout above ₹{s.breakout_level?.toFixed(0)} = aggressive entry<br />
                            🟡 Pullback to ₹{s.pullback_level?.toFixed(0)} (MA20) = conservative entry<br />
                            🔴 Stop Loss: ₹{s.stop_loss?.toFixed(2)} | 🎯 Target: ₹{s.target?.toFixed(2)} | R:R: {rr}
                          </div>
                        </td>
                      </tr>
                    )
                  ];
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
