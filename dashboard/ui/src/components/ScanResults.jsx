import { useState } from "react";
import { useFetch, api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";

const SIG = { STRONG_BUY:"badge-green", BUY:"badge-green", WATCH:"badge-blue", SKIP:"badge-muted" };
const CONF = { high:"badge-green", medium:"badge-yellow", low:"badge-muted" };

export default function ScanResults() {
  const { data, loading, refetch } = useFetch("/scans?limit=200");
  const [adding, setAdding] = useState(null);
  const [sigFilter, setSigFilter] = useState("all");
  const toast = useToast();

  async function addToWatchlist(scan) {
    setAdding(scan.id);
    try {
      await api.post("/watchlist", { symbol: scan.symbol, entry_price: scan.entry_price, stop_loss: scan.stop_loss, target: scan.target, entry_score: scan.entry_score, confidence: scan.confidence });
      toast(`${scan.symbol} added to watchlist`, "success");
    } catch { toast("Failed to add", "error"); }
    finally { setAdding(null); }
  }

  if (loading) return <div style={{ display:"flex", justifyContent:"center", padding:80 }}><span className="spin" style={{ width:32, height:32, borderWidth:3 }} /></div>;

  const scans = data || [];
  const filtered = sigFilter === "all" ? scans : scans.filter(s => s.recommendation === sigFilter);
  const strongBuy = scans.filter(s => s.recommendation === "STRONG_BUY").length;
  const buy       = scans.filter(s => s.recommendation === "BUY").length;

  return (
    <div>
      <div className="stats-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px,1fr))" }}>
        <div className="stat stat-blue"><div className="stat-label">Total Scanned</div><div className="stat-value">{scans.length}</div><div className="stat-sub">latest signals</div></div>
        <div className="stat stat-green"><div className="stat-label">Strong Buy</div><div className="stat-value" style={{ color:"var(--green)" }}>{strongBuy}</div><div className="stat-sub">score ≥ 70</div></div>
        <div className="stat stat-yellow"><div className="stat-label">Buy</div><div className="stat-value" style={{ color:"var(--yellow)" }}>{buy}</div><div className="stat-sub">score 55–70</div></div>
        <div className="stat stat-purple"><div className="stat-label">Avg Score</div>
          <div className="stat-value">{scans.length ? (scans.reduce((s,x) => s+(x.entry_score||0),0)/scans.length).toFixed(0) : "—"}</div>
          <div className="stat-sub">across all signals</div>
        </div>
      </div>

      <div className="section-header">
        <div>
          <div className="section-title">Scan Results</div>
          <div className="section-sub">Signals from morning scans — click "+ Watch" to track</div>
        </div>
        <button className="btn" onClick={refetch}>↻ Refresh</button>
      </div>

      <div className="pills">
        {["all","STRONG_BUY","BUY","WATCH"].map(f => (
          <button key={f} className={`pill ${sigFilter===f?"active":""}`} onClick={() => setSigFilter(f)}>
            {f === "all" ? `All (${scans.length})` : `${f} (${scans.filter(s=>s.recommendation===f).length})`}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty"><div className="empty-icon">🔍</div><div className="empty-text">No scan results yet. Run the morning scan to see signals.</div></div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="right">Score</th>
                  <th>Signal</th>
                  <th>Confidence</th>
                  <th className="right">Entry</th>
                  <th className="right">Stop Loss</th>
                  <th className="right">Target</th>
                  <th className="right">R:R</th>
                  <th className="right">Sentiment</th>
                  <th>Scanned</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(s => {
                  const rr = s.entry_price && s.stop_loss && s.target && s.entry_price > s.stop_loss
                    ? ((s.target - s.entry_price) / (s.entry_price - s.stop_loss)).toFixed(1) : "—";
                  const rrNum = +rr;
                  return (
                    <tr key={s.id}>
                      <td><span style={{ fontWeight:600 }}>{s.symbol}</span></td>
                      <td className="right">
                        <span style={{ fontWeight:700, color: s.entry_score>=70?"var(--green)":s.entry_score>=55?"var(--yellow)":"var(--red)" }}>
                          {s.entry_score?.toFixed(1)}
                        </span>
                      </td>
                      <td><span className={`badge ${SIG[s.recommendation]||"badge-muted"}`}>{s.recommendation}</span></td>
                      <td><span className={`badge ${CONF[s.confidence]||"badge-muted"}`}>{s.confidence}</span></td>
                      <td className="right" style={{ fontVariantNumeric:"tabular-nums" }}>₹{s.entry_price?.toFixed(2)}</td>
                      <td className="right neg" style={{ fontVariantNumeric:"tabular-nums" }}>₹{s.stop_loss?.toFixed(2)}</td>
                      <td className="right pos" style={{ fontVariantNumeric:"tabular-nums" }}>₹{s.target?.toFixed(2)}</td>
                      <td className="right">
                        <span style={{ color: rrNum>=2?"var(--green)":rrNum>=1.5?"var(--yellow)":"var(--red)", fontWeight:600 }}>{rr}</span>
                      </td>
                      <td className="right" style={{ color:"var(--text2)" }}>{s.sentiment_score?.toFixed(0)}</td>
                      <td style={{ color:"var(--muted)", fontSize:12 }}>{s.scanned_at?.slice(0,16).replace("T"," ")}</td>
                      <td>
                        {["STRONG_BUY","BUY"].includes(s.recommendation) && (
                          <button className="btn btn-sm btn-green" disabled={adding===s.id} onClick={() => addToWatchlist(s)}>
                            {adding===s.id ? <span className="spin" /> : "+ Watch"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
