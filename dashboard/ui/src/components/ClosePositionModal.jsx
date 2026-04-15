import { useState } from "react";
import { api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";

export default function ClosePositionModal({ stock, onClose, onClosed }) {
  const [exitPrice, setExitPrice] = useState(stock.live_price?.toFixed(2) || stock.entry_price || "");
  const [reason, setReason] = useState("MANUAL");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const pnl = exitPrice && stock.entry_price
    ? (((+exitPrice - stock.entry_price) / stock.entry_price) * 100).toFixed(2) : null;
  const pnlAmt = exitPrice && stock.entry_price
    ? (+exitPrice - stock.entry_price).toFixed(2) : null;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post(`/watchlist/${stock.symbol}/close`, { exit_price: +exitPrice, reason });
      toast(`${stock.symbol} closed | PnL: ${pnl}%`, +pnl >= 0 ? "success" : "error");
      onClosed(); onClose();
    } catch { toast("Failed to close", "error"); }
    finally { setSaving(false); }
  }

  return (
    <div className="overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-title">Close Position — {stock.symbol}</div>
        <div style={{ display: "flex", gap: 20, marginBottom: 20, padding: "12px 16px", background: "var(--bg2)", borderRadius: "var(--radius-sm)", fontSize: 13 }}>
          <span style={{ color: "var(--text2)" }}>Entry <strong style={{ color: "var(--text)" }}>₹{stock.entry_price?.toFixed(2)}</strong></span>
          <span style={{ color: "var(--text2)" }}>SL <strong className="neg">₹{stock.stop_loss?.toFixed(2)}</strong></span>
          <span style={{ color: "var(--text2)" }}>Target <strong className="pos">₹{stock.target?.toFixed(2)}</strong></span>
        </div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Exit Price *</label>
              <input className="input" type="number" step="0.01"
                value={exitPrice} onChange={e => setExitPrice(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Reason</label>
              <select className="input" value={reason} onChange={e => setReason(e.target.value)}>
                <option value="MANUAL">Manual Exit</option>
                <option value="TARGET_HIT">Target Hit</option>
                <option value="STOP_LOSS_HIT">Stop Loss Hit</option>
                <option value="TRAILING_STOP">Trailing Stop</option>
                <option value="CAUTION">Caution Signal</option>
              </select>
            </div>
          </div>

          {pnl !== null && (
            <div style={{ margin: "16px 0", padding: "18px", background: "var(--bg2)", borderRadius: "var(--radius-sm)", textAlign: "center" }}>
              <div style={{ fontSize: 32, fontWeight: 700 }} className={+pnl >= 0 ? "pos" : "neg"}>
                {+pnl >= 0 ? "+" : ""}{pnl}%
              </div>
              <div style={{ fontSize: 13, color: "var(--text2)", marginTop: 4 }}>
                ₹{pnlAmt} per share
              </div>
            </div>
          )}

          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-red" disabled={saving}>
              {saving ? <span className="spin" /> : "Close Position"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
