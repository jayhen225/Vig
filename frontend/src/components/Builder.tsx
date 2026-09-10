import { useState } from "react";
import { PriceError, PriceResult, SlipLeg, fmtAmerican, fmtPct, priceParlay, slipLegToApiLeg } from "../api";
import { Close, Plus } from "./icons";
import Tracker, { useTracker } from "./Tracker";

const decProfit = (a: number) => (a > 0 ? a / 100 : 100 / -a);
const decimalOdds = (a: number) => 1 + decProfit(a);
const decimalToAmerican = (d: number) => (d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1)));
const isError = (r: PriceResult | PriceError | null): r is PriceError =>
  !!r && "error" in r;

function gameKey(l: SlipLeg): string | null {
  return l.kind === "prop" ? (l.opponent ?? l.team) : `${l.home_team} @ ${l.away_team}`;
}

function legLabel(l: SlipLeg): string {
  if (l.kind === "prop") return `${l.player} ${l.side === "over" ? "Over" : "Under"} ${l.line} ${l.market_label}`;
  if (l.market === "totals") return `${l.home_team} @ ${l.away_team} ${l.side} ${l.line}`;
  const linePart = l.line != null ? ` ${l.line > 0 ? "+" : ""}${l.line}` : "";
  return `${l.side}${linePart} ${l.market_label}`;
}

export default function Builder({
  slip,
  onRemove,
  onGoBoard,
}: {
  slip: SlipLeg[];
  onRemove: (id: string) => void;
  onGoBoard: () => void;
}) {
  const [result, setResult] = useState<PriceResult | PriceError | null>(null);
  const [loading, setLoading] = useState(false);
  const [stake, setStake] = useState(100);
  const tracker = useTracker();

  const sameGame = slip.length > 1 && new Set(slip.map(gameKey)).size === 1 && gameKey(slip[0]);

  const legPrices = slip.map((l) => l.price).filter((p): p is number => p != null);
  const combinedDecimal = legPrices.length ? legPrices.reduce((acc, p) => acc * decimalOdds(p), 1) : null;
  const combinedAmerican = combinedDecimal != null && combinedDecimal > 1 ? decimalToAmerican(combinedDecimal) : null;
  const payout = combinedDecimal != null ? Math.round(stake * combinedDecimal) : null;

  async function price() {
    if (slip.length === 0) return;
    setLoading(true);
    try {
      const r = await priceParlay(slip.map(slipLegToApiLeg));
      setResult(r);
    } finally {
      setLoading(false);
    }
  }

  function saveToTracker() {
    if (!result || isError(result)) return;
    tracker.add({
      stake,
      legLabels: slip.map(legLabel),
      combinedPrice: combinedAmerican,
      fairPrice: result.fair_price,
      edgePct: Math.round(result.correlation_edge * 1000) / 10,
    });
  }

  return (
    <div style={{ flexGrow: 1, display: "flex", minHeight: 0 }}>
      {/* Slip */}
      <div
        style={{
          width: 420,
          flexShrink: 0,
          borderRight: "1px solid var(--hair)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ padding: "26px 26px 18px" }}>
          <div style={{ fontSize: 13, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.8px" }}>
            Bet slip
          </div>
          <div style={{ fontSize: 20, fontWeight: 600, marginTop: 6 }}>
            {slip.length} {slip.length === 1 ? "leg" : "legs"}
            {sameGame ? " · same game" : ""}
          </div>
        </div>

        <div style={{ padding: "0 26px", display: "flex", flexDirection: "column", gap: 12, flexGrow: 1, overflowY: "auto" }}>
          {slip.map((l) => (
            <div key={l.id} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 16 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: 15 }}>
                    {l.kind === "prop" ? l.player : `${l.away_team} @ ${l.home_team}`}
                  </div>
                  <div className="mono" style={{ color: "var(--faint)", fontSize: 11.5, marginTop: 3 }}>
                    {l.kind === "prop"
                      ? [l.team, l.position, l.opponent].filter(Boolean).join(" · ")
                      : l.market_label}
                  </div>
                </div>
                <button className="leg-x" onClick={() => onRemove(l.id)} aria-label="remove leg">
                  <Close />
                </button>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 14 }}>
                <span
                  className="mono"
                  style={{ padding: "5px 11px", borderRadius: 7, background: "var(--greenSoft)", color: "var(--green)", fontSize: 12.5 }}
                >
                  {l.kind === "prop"
                    ? `${l.side.toUpperCase()} ${l.line}`
                    : `${l.side}${l.line != null ? ` ${l.line > 0 ? "+" : ""}${l.line}` : ""}`}
                </span>
                {l.kind === "prop" && <span style={{ color: "var(--muted)", fontSize: 12.5 }}>{l.market_label}</span>}
                <span style={{ flexGrow: 1 }} />
                <span className="mono" style={{ fontSize: 13, color: "var(--muted)" }}>
                  {fmtAmerican(l.price)}
                </span>
              </div>
            </div>
          ))}

          <button
            onClick={onGoBoard}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              padding: "15px 16px",
              border: "1px dashed var(--border)",
              borderRadius: 12,
              color: "var(--faint)",
              fontSize: 13.5,
            }}
          >
            <Plus stroke="#565f6d" /> Add a leg from the board…
          </button>
        </div>

        {/* Combined-odds calculator -- always available, independent of correlation pricing */}
        <div style={{ padding: "0 26px 18px", borderTop: "1px solid var(--hair)", paddingTop: 18 }}>
          <div style={{ fontSize: 12, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.7px", marginBottom: 10 }}>
            Calculator
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ color: "var(--muted)", fontSize: 13 }}>Stake</span>
            <div style={{ display: "flex", alignItems: "center", border: "1px solid var(--border)", borderRadius: 8, padding: "6px 10px" }}>
              <span className="mono" style={{ color: "var(--faint)", fontSize: 13 }}>$</span>
              <input
                type="number"
                value={stake}
                onChange={(e) => setStake(Math.max(0, Number(e.target.value) || 0))}
                className="mono"
                style={{ border: "none", outline: "none", background: "transparent", color: "var(--text)", fontSize: 13, width: 70 }}
              />
            </div>
            <span style={{ flexGrow: 1 }} />
            <span className="mono" style={{ fontSize: 13, color: "var(--muted)" }}>{fmtAmerican(combinedAmerican)}</span>
          </div>
          <div style={{ marginTop: 8, fontSize: 13, color: "var(--muted)" }}>
            Payout{" "}
            <b className="mono" style={{ color: "var(--text)" }}>
              {payout != null ? `$${payout}` : "—"}
            </b>
          </div>
        </div>

        <div style={{ padding: "22px 26px" }}>
          <button
            className="pricebtn"
            onClick={price}
            disabled={slip.length === 0 || loading}
            style={{
              width: "100%",
              height: 48,
              borderRadius: 11,
              background: slip.length ? "var(--green)" : "var(--panel)",
              color: slip.length ? "#07130c" : "var(--faint)",
              fontWeight: 600,
              fontSize: 15,
            }}
          >
            {loading ? "Pricing…" : "Price parlay"}
          </button>
        </div>
      </div>

      {/* Analysis + Tracker */}
      <div style={{ flexGrow: 1, padding: "44px 48px", display: "flex", flexDirection: "column", overflowY: "auto" }}>
        {!result && <Empty />}
        {isError(result) && <Unsupported err={result} />}
        {result && !isError(result) && <Analysis r={result} onSave={saveToTracker} />}
        <Tracker parlays={tracker.parlays} onSetStatus={tracker.setStatus} onRemove={tracker.remove} />
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div style={{ color: "var(--faint)", fontSize: 15, maxWidth: 520, lineHeight: 1.6 }}>
      <div style={{ fontSize: 20, color: "var(--muted)", marginBottom: 10 }}>No parlay priced yet</div>
      Add legs to the slip and hit <b style={{ color: "var(--green)" }}>Price parlay</b>. The model compares the
      book's independent price against the correlation-aware price — the gap is the edge.
    </div>
  );
}

function Unsupported({ err }: { err: PriceError }) {
  return (
    <div style={{ color: "var(--muted)", fontSize: 15, maxWidth: 560, lineHeight: 1.6 }}>
      <div style={{ fontSize: 20, color: "var(--neg)", marginBottom: 10 }}>Can't price this slip</div>
      {err.message}
      <div className="mono" style={{ marginTop: 12, fontSize: 13, color: "var(--faint)" }}>
        unsupported: {err.unsupported.join(", ")}
      </div>
    </div>
  );
}

function Analysis({ r, onSave }: { r: PriceResult; onSave: () => void }) {
  const edgePts = (r.correlation_edge * 100).toFixed(1);
  const positive = r.correlation_edge >= 0;
  const stake = 100;
  const bookPay = r.book_price != null ? Math.round(stake * (1 + decProfit(r.book_price))) : null;
  const fairPay = r.fair_price != null ? Math.round(stake * (1 + decProfit(r.fair_price))) : null;
  const evPer =
    r.book_price != null ? r.correlated_prob * decProfit(r.book_price) - (1 - r.correlated_prob) : null;

  return (
    <>
      {r.source === "estimate" && (
        <div
          style={{
            marginBottom: 22,
            padding: "9px 13px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            color: "var(--muted)",
            fontSize: 12.5,
            display: "inline-block",
          }}
        >
          Estimate — trained models not loaded on this server. Correlation structure is real; player projections are approximate.
        </div>
      )}

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div style={{ fontSize: 13, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.9px" }}>
          Correlation edge
        </div>
        <button
          onClick={onSave}
          style={{
            padding: "7px 14px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            color: "var(--muted)",
            fontSize: 12.5,
          }}
        >
          Save to tracker
        </button>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 18, marginTop: 10 }}>
        <div
          className="mono"
          style={{
            fontSize: 88,
            fontWeight: 600,
            lineHeight: 0.9,
            color: positive ? "var(--green)" : "var(--neg)",
            textShadow: positive ? "0 0 34px rgba(53,224,138,0.35)" : "none",
          }}
        >
          {positive ? "+" : ""}
          {edgePts}
          <span style={{ fontSize: 40 }}>pts</span>
        </div>
        <span
          style={{
            padding: "7px 14px",
            borderRadius: 8,
            background: positive ? "var(--greenSoft)" : "transparent",
            border: positive ? "1px solid var(--greenLine)" : "1px solid var(--border)",
            color: positive ? "var(--green)" : "var(--muted)",
            fontSize: 13.5,
            fontWeight: 500,
          }}
        >
          {positive ? "＋EV · underpriced" : "no edge"}
        </span>
      </div>
      <div style={{ color: "var(--muted)", fontSize: 15, marginTop: 18, maxWidth: 640, lineHeight: 1.6 }}>
        The book prices these legs as independent. Priced with the shared game script, the parlay hits{" "}
        <b style={{ color: "var(--text)" }}>{fmtPct(r.correlated_prob)}</b> of the time versus the book's{" "}
        <b style={{ color: "var(--text)" }}>{fmtPct(r.independent_prob)}</b>.
      </div>

      {/* comparison track */}
      <div style={{ marginTop: 42, maxWidth: 680 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 14 }}>
          <span style={{ color: "var(--muted)" }}>
            Book <span className="mono" style={{ color: "var(--text)" }}>{fmtPct(r.independent_prob)}</span>{" "}
            <span style={{ color: "var(--faint)" }}>({fmtAmerican(r.book_price)})</span>
          </span>
          <span style={{ color: "var(--green)" }}>
            Model <span className="mono">{fmtPct(r.correlated_prob)}</span>{" "}
            <span style={{ color: "var(--faint)" }}>(fair {fmtAmerican(r.fair_price)})</span>
          </span>
        </div>
        <div style={{ height: 10, borderRadius: 6, background: "var(--panel)", position: "relative", overflow: "hidden" }}>
          <div style={{ position: "absolute", left: 0, top: 0, height: 10, width: `${r.independent_prob * 100}%`, background: "var(--faint)", borderRadius: 6 }} />
          <div style={{ position: "absolute", left: 0, top: 0, height: 10, width: `${r.correlated_prob * 100}%`, background: "var(--green)", borderRadius: 6, opacity: 0.9 }} />
        </div>
      </div>

      {/* per-leg */}
      <div style={{ marginTop: 38, maxWidth: 680, borderTop: "1px solid var(--hair)" }}>
        {r.individual.map((leg, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr",
              padding: "16px 2px",
              alignItems: "center",
              borderBottom: i < r.individual.length - 1 ? "1px solid var(--hair)" : "none",
            }}
          >
            <span style={{ fontSize: 14 }}>
              {leg.player ?? leg.team ?? leg.market} {leg.side === "over" ? "Over" : leg.side === "under" ? "Under" : ""}{" "}
              {leg.line ?? ""}
            </span>
            <span className="mono" style={{ textAlign: "right", fontSize: 14 }}>
              {fmtPct(leg.prob)}
            </span>
          </div>
        ))}
      </div>

      <div style={{ flexGrow: 1 }} />
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 22,
          color: "var(--muted)",
          fontSize: 13.5,
          borderTop: "1px solid var(--hair)",
          paddingTop: 20,
          marginTop: 28,
        }}
      >
        <span>$100 stake →</span>
        <span>
          book pays <b className="mono" style={{ color: "var(--text)" }}>${bookPay ?? "—"}</b>
        </span>
        <span style={{ color: "var(--faint)" }}>·</span>
        <span>
          model-fair <b className="mono" style={{ color: "var(--green)" }}>${fairPay ?? "—"}</b>
        </span>
        {evPer != null && (
          <>
            <span style={{ color: "var(--faint)" }}>·</span>
            <span>
              edge{" "}
              <b className="mono" style={{ color: evPer >= 0 ? "var(--green)" : "var(--neg)" }}>
                {evPer >= 0 ? "+" : ""}${evPer.toFixed(2)}
              </b>{" "}
              per $1
            </span>
          </>
        )}
      </div>
    </>
  );
}
