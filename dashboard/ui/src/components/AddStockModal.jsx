import { useState } from "react";
import { api } from "../hooks/useApi";
import { useToast } from "../hooks/useToast";

const EMPTY = { symbol: "", entry_price: "", stop_loss: "", target: "", confidence: "medium", notes: "" };

export default function AddStockModal({ onClose, onAdded }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const ep = +form.entry_price, sl = +form.stop_loss, tg = +form.target;
  const rr      = ep && sl && tg && ep > sl ? ((tg - ep) / (ep - sl)).toFixed(2) : null;
  const upside  = ep && tg  ? (((tg - ep) / ep) * 100).toFixed(1) : null;
  const downside= ep && sl  ? (((ep - sl) / ep) * 100).toFixed(1) : null;
  const rrOk    = rr && +rr >= 1.5;

  async function submit(e) {
    e.preventDefault();
    if (!form.symbol || !ep || !sl || !tg) { toast("Fill all required fields", "error"); return; }
    if (sl >= ep) { toast("Stop loss must be below entry", "error"); return; }
    if (tg <= ep) { toast("Target must be above entry", "error"); return; }
    setSaving(true);
    try {
      await api.post("/watchlist", { ...form, symbol: form.symbol.toUpperCase().trim(), entry_price: ep, stop_loss: sl, target: tg });
      toast(`${form.symbol.toUpperCase()} added`, "success");
      onAdded(); onClose();
    } catch { toast("Failed to add", "error"); }
    finally { setSaving(false); }
  }

  return (
    <div className="overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-title">Add to Watchlist</div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <div className="form-group full">
              <label className="form-label">Symbol *</label>
              <input className="input" placeholder="e.g. INFY.NS"
                value={form.symbol} onChange={e => set("symbol", e.target.value.toUpperCase())} />
            </div>
            <div className="form-group">
              <label className="form-label">Entry Price *</label>
              <input className="input" type="number" step="0.01" placeholder="₹"
                value={form.entry_price} onChange={e => set("entry_price", e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Stop Loss *</label>
              <input className="input" type="number" step="0.01" placeholder="₹"
                value={form.stop_loss} onChange={e => set("stop_loss", e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Target *</label>
              <input className="input" type="number" step="0.01" placeholder="₹"
                value={form.target} onChange={e => set("target", e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Confidence</label>
              <select className="input" value={form.confidence} onChange={e => set("confidence", e.target.value)}>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div className="form-group full">
              <label className="form-label">Notes</label>
              <input className="input" placeholder="Optional" value={form.notes} onChange={e => set("notes", e.target.value)} />
            </div>
          </div>

          {rr && (
            <div style={{ margin: "16px 0", padding: "14px 16px", background: "var(--bg2)", borderRadius: "var(--radius-sm)", display: "flex", gap: 24, alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>RISK:REWARD</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: rrOk ? "var(--green)" : "var(--red)" }}>{rr}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>UPSIDE</div>
                <div className="pos">+{upside}%</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>DOWNSIDE</div>
                <div className="neg">-{downside}%</div>
              </div>
              {!rrOk && <div style={{ fontSize: 12, color: "var(--yellow)", marginLeft: "auto" }}>⚠ R:R below 1.5 — weak setup</div>}
            </div>
          )}

          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? <span className="spin" /> : "Add Stock"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
