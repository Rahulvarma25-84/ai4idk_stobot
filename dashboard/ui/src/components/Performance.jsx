import { useFetch, api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";
import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid, ReferenceLine, Cell, ScatterChart, Scatter, ZAxis } from "recharts";

const Tip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div style={{ background:"var(--surface2)", border:"1px solid var(--border2)", borderRadius:8, padding:"8px 12px", fontSize:12 }}>
      <div style={{ color:v>=0?"var(--green)":"var(--red)", fontWeight:700 }}>{v>=0?"+":""}{v?.toFixed(2)}%</div>
    </div>
  );
};

export default function Performance() {
  const { data, loading } = useFetch("/performance");
  const [running, setRunning] = useState(false);
  const toast = useToast();

  async function runReplacement() {
    setRunning(true);
    try {
      const r = await api.post("/replacement", {});
      toast(r.length ? `${r.length} replacement suggestion(s) sent` : "No replacements needed", r.length ? "info" : "success");
    } catch { toast("Failed", "error"); }
    finally { setRunning(false); }
  }

  if (loading) return <div style={{ display:"flex", justifyContent:"center", padding:80 }}><span className="spin" style={{ width:32, height:32, borderWidth:3 }} /></div>;

  const p = data || {};
  if (!p.total_trades) return (
    <div>
      <div className="section-header">
        <div className="section-title">Performance</div>
        <button className="btn" onClick={runReplacement} disabled={running}>
          {running ? <span className="spin" /> : "🔁"} Check Replacements
        </button>
      </div>
      <div className="empty"><div className="empty-icon">📊</div><div className="empty-text">No closed trades yet.</div></div>
    </div>
  );

  const trades = p.trades || [];
  let cum = 0;
  const curve = trades.map((t, i) => {
    cum += t.pnl_percent || 0;
    return { i: i+1, sym: t.symbol, pnl: t.pnl_percent, cum: +cum.toFixed(2) };
  });

  return (
    <div>
      <div className="section-header">
        <div className="section-title">Performance</div>
        <button className="btn" onClick={runReplacement} disabled={running}>
          {running ? <span className="spin" /> : "🔁"} Check Replacements
        </button>
      </div>

      <div className="stats-grid">
        <div className="stat stat-blue"><div className="stat-label">Total Trades</div><div className="stat-value">{p.total_trades}</div><div className="stat-sub">{p.winning_trades}W / {p.losing_trades}L</div></div>
        <div className={`stat ${p.win_rate>=50?"stat-green":"stat-red"}`}>
          <div className="stat-label">Win Rate</div>
          <div className="stat-value" style={{ color:p.win_rate>=50?"var(--green)":"var(--red)" }}>{p.win_rate}%</div>
        </div>
        <div className={`stat ${p.avg_pnl>=0?"stat-green":"stat-red"}`}>
          <div className="stat-label">Avg PnL</div>
          <div className="stat-value" style={{ color:p.avg_pnl>=0?"var(--green)":"var(--red)" }}>{p.avg_pnl>=0?"+":""}{p.avg_pnl}%</div>
        </div>
        <div className={`stat ${p.total_pnl>=0?"stat-green":"stat-red"}`}>
          <div className="stat-label">Total PnL</div>
          <div className="stat-value" style={{ color:p.total_pnl>=0?"var(--green)":"var(--red)" }}>{p.total_pnl>=0?"+":""}{p.total_pnl}%</div>
        </div>
        <div className="stat stat-purple">
          <div className="stat-label">Profit Factor</div>
          <div className="stat-value" style={{ color:p.profit_factor>=1.5?"var(--green)":p.profit_factor>=1?"var(--yellow)":"var(--red)" }}>{p.profit_factor}</div>
          <div className="stat-sub">gross profit / gross loss</div>
        </div>
        <div className="stat stat-yellow">
          <div className="stat-label">Avg Hold</div>
          <div className="stat-value">{p.avg_holding_days}d</div>
          <div className="stat-sub">days per trade</div>
        </div>
        <div className="stat stat-red">
          <div className="stat-label">Max Drawdown</div>
          <div className="stat-value neg">-{p.max_drawdown?.toFixed(1)}%</div>
        </div>
        {p.best_trade && <div className="stat stat-green"><div className="stat-label">Best Trade</div><div className="stat-value pos">+{p.best_trade.pnl_percent?.toFixed(2)}%</div><div className="stat-sub">{p.best_trade.symbol}</div></div>}
        {p.worst_trade && <div className="stat stat-red"><div className="stat-label">Worst Trade</div><div className="stat-value neg">{p.worst_trade.pnl_percent?.toFixed(2)}%</div><div className="stat-sub">{p.worst_trade.symbol}</div></div>}
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, marginBottom:20 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Per-Trade PnL</span></div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={curve} margin={{ top:4, right:4, bottom:4, left:0 }}>
                <XAxis dataKey="sym" tick={false} axisLine={false} />
                <YAxis tick={{ fill:"var(--muted)", fontSize:11 }} axisLine={false} tickLine={false} />
                <Tooltip content={<Tip />} />
                <ReferenceLine y={0} stroke="var(--border2)" />
                <Bar dataKey="pnl" radius={[3,3,0,0]}>
                  {curve.map((e,i) => <Cell key={i} fill={e.pnl>=0?"var(--green)":"var(--red)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="card">
          <div className="card-header"><span className="card-title">Equity Curve</span></div>
          <div className="card-body">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={curve} margin={{ top:4, right:4, bottom:4, left:0 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="i" tick={{ fill:"var(--muted)", fontSize:11 }} axisLine={false} />
                <YAxis tick={{ fill:"var(--muted)", fontSize:11 }} axisLine={false} tickLine={false} />
                <Tooltip content={<Tip />} />
                <ReferenceLine y={0} stroke="var(--border2)" />
                <Line type="monotone" dataKey="cum" stroke="var(--blue)" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header"><span className="card-title">Trade Log</span></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>Action</th>
                <th className="right">Exit Price</th><th className="right">PnL</th>
                <th className="right">Entry Score</th><th className="right">Hold Days</th>
                <th>Reason</th><th>Date</th>
              </tr>
            </thead>
            <tbody>
              {[...trades].reverse().map(t => (
                <tr key={t.id}>
                  <td><strong>{t.symbol}</strong></td>
                  <td><span className={`badge ${t.action==="EXIT"?"badge-red":"badge-green"}`}>{t.action}</span></td>
                  <td className="right" style={{ fontVariantNumeric:"tabular-nums" }}>₹{t.price?.toFixed(2)}</td>
                  <td className="right">
                    {t.pnl_percent!=null
                      ? <span className={t.pnl_percent>=0?"pos":"neg"}>{t.pnl_percent>=0?"+":""}{t.pnl_percent?.toFixed(2)}%</span>
                      : <span className="neu">—</span>}
                  </td>
                  <td className="right" style={{ color:"var(--text2)" }}>{t.entry_score?.toFixed(0)||"—"}</td>
                  <td className="right" style={{ color:"var(--text2)" }}>{t.holding_days||"—"}</td>
                  <td style={{ color:"var(--text2)" }}>{t.exit_reason||"—"}</td>
                  <td style={{ color:"var(--muted)", fontSize:12 }}>{t.timestamp?.slice(0,16).replace("T"," ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
