import { useMemo, useState } from "react";
import { Board as BoardData, BoardRow, fmtAmerican } from "../api";
import { Plus, Search } from "./icons";

const cols = "2.4fr 1.3fr 1.6fr 1.2fr 1.5fr 0.9fr 48px";

export default function Board({
  data,
  inSlip,
  onAdd,
}: {
  data: BoardData;
  inSlip: (id: string) => boolean;
  onAdd: (row: BoardRow) => void;
}) {
  const [q, setQ] = useState("");
  const rows = useMemo(
    () => data.rows.filter((r) => r.player.toLowerCase().includes(q.toLowerCase())),
    [data.rows, q],
  );

  return (
    <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* title + summary */}
      <div
        style={{
          padding: "34px 32px 22px",
          flexShrink: 0,
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 24,
        }}
      >
        <div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.3px" }}>
            This week's mispriced props
          </div>
          <div style={{ color: "var(--muted)", fontSize: 14, marginTop: 8 }}>
            <span className="mono" style={{ color: "var(--green)", fontWeight: 500 }}>
              {data.stats.ev_count}
            </span>{" "}
            +EV props · avg edge{" "}
            <span className="mono" style={{ color: "var(--green)", fontWeight: 500 }}>
              +{data.stats.avg_edge}%
            </span>{" "}
            · <span className="mono">{data.stats.games_live}/{data.stats.games_total}</span> games ·{" "}
            {data.stats.books} books
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 9,
            padding: "10px 14px",
            border: "1px solid var(--border)",
            borderRadius: 9,
            width: 240,
          }}
        >
          <Search />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search player…"
            style={{
              border: "none",
              outline: "none",
              background: "transparent",
              color: "var(--text)",
              fontSize: 13.5,
              width: "100%",
            }}
          />
        </div>
      </div>

      {/* table */}
      <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", minHeight: 0, padding: "0 32px 24px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: cols,
            padding: "0 20px 14px",
            color: "var(--faint)",
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.8px",
          }}
        >
          <div>Player</div>
          <div>Matchup</div>
          <div>Market</div>
          <div>Book</div>
          <div style={{ textAlign: "right" }}>Price → Fair</div>
          <div style={{ textAlign: "right" }}>Edge</div>
          <div />
        </div>

        <div style={{ flexGrow: 1, overflowY: "auto", borderTop: "1px solid var(--hair)" }}>
          {rows.map((r) => {
            const added = inSlip(r.id);
            const pos = r.edge_pct >= 0;
            return (
              <div
                key={r.id}
                className="row"
                style={{
                  display: "grid",
                  gridTemplateColumns: cols,
                  alignItems: "center",
                  padding: "16px 20px",
                  borderBottom: "1px solid var(--hair)",
                  opacity: pos ? 1 : 0.6,
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  <span style={{ fontWeight: 500, fontSize: 15 }}>{r.player}</span>
                  <span className="mono" style={{ color: "var(--faint)", fontSize: 11.5 }}>
                    {[r.team, r.position].filter(Boolean).join(" · ") || "—"}
                  </span>
                </div>
                <div className="mono" style={{ color: "var(--muted)", fontSize: 12.5 }}>
                  {r.opponent ?? "—"}
                </div>
                <div>
                  <span style={{ fontSize: 13.5 }}>{r.market_label}</span>{" "}
                  <span className="mono" style={{ color: "var(--faint)", fontSize: 12.5, marginLeft: 4 }}>
                    {r.side === "over" ? "o" : "u"}
                    {r.line}
                  </span>
                </div>
                <div style={{ color: "var(--muted)", fontSize: 13 }}>{r.book ?? "—"}</div>
                <div className="mono" style={{ textAlign: "right", fontSize: 13 }}>
                  {fmtAmerican(r.price)} <span style={{ color: "var(--faint)" }}>→ {fmtAmerican(r.fair_price)}</span>
                </div>
                <div
                  className="mono"
                  style={{
                    textAlign: "right",
                    fontSize: 16,
                    fontWeight: 600,
                    color: pos ? "var(--green)" : "var(--neg)",
                  }}
                >
                  {pos ? "+" : ""}
                  {r.edge_pct}%
                </div>
                <div style={{ textAlign: "right" }}>
                  <button
                    className="addbtn"
                    onClick={() => onAdd(r)}
                    disabled={!r.priceable || added}
                    title={
                      !r.priceable
                        ? "Market not supported by the pricer"
                        : added
                          ? "In slip"
                          : "Add to slip"
                    }
                    style={{
                      display: "inline-flex",
                      width: 30,
                      height: 30,
                      borderRadius: 8,
                      background: added ? "var(--green)" : "transparent",
                      border: added ? "none" : "1px solid var(--border)",
                      alignItems: "center",
                      justifyContent: "center",
                      opacity: r.priceable ? 1 : 0.35,
                    }}
                  >
                    <Plus stroke={added ? "#08130c" : "#35e08a"} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
