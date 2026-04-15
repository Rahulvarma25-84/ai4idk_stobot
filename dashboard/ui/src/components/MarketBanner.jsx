import { useFetch } from "../hooks/useApi";

export default function MarketBanner() {
  const { data } = useFetch("/market");
  if (!data) return null;
  const bull = data.bullish;
  return (
    <div className={`regime ${bull ? "regime-bull" : "regime-bear"}`}>
      <div className="regime-dot" />
      <span style={{ fontWeight: 600, color: bull ? "var(--green)" : "var(--red)" }}>
        {bull ? "BULLISH" : "BEARISH"} MARKET
      </span>
      <span style={{ color: "var(--text2)" }}>
        Nifty 50 &nbsp;
        <strong style={{ color: "var(--text)" }}>
          ₹{data.nifty_price?.toLocaleString("en-IN")}
        </strong>
      </span>
      <span style={{ color: "var(--text2)" }}>
        MA20 ₹{data.ma20?.toLocaleString("en-IN")}
      </span>
      <span className={bull ? "pos" : "neg"}>
        {data.pct_above_ma > 0 ? "+" : ""}{data.pct_above_ma}% vs MA20
      </span>
      {!bull && (
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--red)" }}>
          ⚠ BUY signals suppressed in bearish regime
        </span>
      )}
    </div>
  );
}
