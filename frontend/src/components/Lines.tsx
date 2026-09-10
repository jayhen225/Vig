import { useMemo } from "react";
import { GameLineRow, GameLines, fmtAmerican } from "../api";
import { Plus } from "./icons";

const cols = "1.8fr 1.4fr 1.4fr 1.4fr";

interface GameGroup {
  event_id: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  h2h: Record<string, GameLineRow>;
  spreads: Record<string, GameLineRow>;
  totals: Record<string, GameLineRow>;
}

function groupByGame(rows: GameLineRow[]): GameGroup[] {
  const games = new Map<string, GameGroup>();
  for (const r of rows) {
    let g = games.get(r.event_id);
    if (!g) {
      g = {
        event_id: r.event_id,
        commence_time: r.commence_time,
        home_team: r.home_team,
        away_team: r.away_team,
        h2h: {},
        spreads: {},
        totals: {},
      };
      games.set(r.event_id, g);
    }
    g[r.market][r.side] = r;
  }
  return [...games.values()].sort((a, b) => a.commence_time.localeCompare(b.commence_time));
}

function Cell({
  row,
  inSlip,
  onAdd,
}: {
  row?: GameLineRow;
  inSlip: (id: string) => boolean;
  onAdd: (row: GameLineRow) => void;
}) {
  if (!row) return <span style={{ color: "var(--faint)" }}>—</span>;
  const pos = row.edge_pct >= 0;
  const added = inSlip(row.id);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span className="mono" style={{ fontSize: 13 }}>
          {row.line != null ? `${row.line > 0 ? "+" : ""}${row.line} ` : ""}
          {fmtAmerican(row.price)}
        </span>
        <span
          className="mono"
          style={{ fontSize: 11, color: pos ? "var(--green)" : "var(--neg)" }}
        >
          {pos ? "+" : ""}
          {row.edge_pct}% · {row.book ?? "—"}
        </span>
      </div>
      <button
        className="addbtn"
        onClick={() => onAdd(row)}
        disabled={!row.priceable || added}
        title={added ? "In slip" : "Add to slip"}
        style={{
          display: "inline-flex",
          width: 24,
          height: 24,
          borderRadius: 7,
          background: added ? "var(--green)" : "transparent",
          border: added ? "none" : "1px solid var(--border)",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <Plus stroke={added ? "#08130c" : "#35e08a"} />
      </button>
    </div>
  );
}

export default function Lines({
  data,
  inSlip,
  onAdd,
}: {
  data: GameLines;
  inSlip: (id: string) => boolean;
  onAdd: (row: GameLineRow) => void;
}) {
  const games = useMemo(() => groupByGame(data.rows), [data.rows]);

  return (
    <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{ padding: "34px 32px 22px", flexShrink: 0 }}>
        <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.3px" }}>
          This week's game lines
        </div>
        <div style={{ color: "var(--muted)", fontSize: 14, marginTop: 8 }}>
          <span className="mono">{data.games}</span> games · {data.books} books
        </div>
      </div>

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
          <div>Matchup</div>
          <div>Moneyline</div>
          <div>Spread</div>
          <div>Total</div>
        </div>

        <div style={{ flexGrow: 1, overflowY: "auto", borderTop: "1px solid var(--hair)" }}>
          {games.map((g) => (
            <div
              key={g.event_id}
              style={{
                display: "grid",
                gridTemplateColumns: cols,
                padding: "16px 20px",
                borderBottom: "1px solid var(--hair)",
                gap: 16,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ fontWeight: 500, fontSize: 14 }}>{g.away_team}</span>
                <span style={{ fontWeight: 500, fontSize: 14 }}>@ {g.home_team}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <Cell row={g.h2h[g.away_team]} inSlip={inSlip} onAdd={onAdd} />
                <Cell row={g.h2h[g.home_team]} inSlip={inSlip} onAdd={onAdd} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <Cell row={g.spreads[g.away_team]} inSlip={inSlip} onAdd={onAdd} />
                <Cell row={g.spreads[g.home_team]} inSlip={inSlip} onAdd={onAdd} />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <Cell row={g.totals["Over"]} inSlip={inSlip} onAdd={onAdd} />
                <Cell row={g.totals["Under"]} inSlip={inSlip} onAdd={onAdd} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
