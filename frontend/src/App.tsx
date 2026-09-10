import { useEffect, useState } from "react";
import { Board as BoardData, BoardRow, GameLines, getBoard, getLines } from "./api";
import Board from "./components/Board";
import Builder from "./components/Builder";
import Lines from "./components/Lines";
import TopBar from "./components/TopBar";

type Tab = "board" | "lines" | "builder";

export default function App() {
  const [tab, setTab] = useState<Tab>("board");
  const [board, setBoard] = useState<BoardData | null>(null);
  const [lines, setLines] = useState<GameLines | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linesError, setLinesError] = useState<string | null>(null);
  const [slip, setSlip] = useState<BoardRow[]>([]);

  useEffect(() => {
    getBoard().then(setBoard).catch((e) => setError(String(e)));
    getLines().then(setLines).catch((e) => setLinesError(String(e)));
  }, []);

  const inSlip = (id: string) => slip.some((l) => l.id === id);
  const addLeg = (row: BoardRow) => setSlip((s) => (inSlip(row.id) ? s : [...s, row]));
  const removeLeg = (id: string) => setSlip((s) => s.filter((l) => l.id !== id));

  const week = board?.week ? `Week ${board.week} · ${board.season}` : "This week";

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--bg)" }}>
      <TopBar tab={tab} onTab={setTab} slipCount={slip.length} week={week} />

      {tab !== "lines" && board && board.source !== "live" && (
        <div
          style={{
            flexShrink: 0,
            padding: "8px 32px",
            background: "var(--greenSoft)",
            borderBottom: "1px solid var(--hair)",
            color: "var(--green)",
            fontSize: 12.5,
          }}
        >
          Sample data — the live warehouse isn't reachable from this server, so the board and prices are illustrative.
        </div>
      )}

      {tab === "lines" && lines && lines.source !== "live" && (
        <div
          style={{
            flexShrink: 0,
            padding: "8px 32px",
            background: "var(--greenSoft)",
            borderBottom: "1px solid var(--hair)",
            color: "var(--green)",
            fontSize: 12.5,
          }}
        >
          Sample data — the live warehouse isn't reachable from this server, so game lines are illustrative.
        </div>
      )}

      {tab === "board" && error && (
        <div style={{ padding: 32, color: "var(--neg)" }}>Couldn't reach the API: {error}</div>
      )}
      {tab === "board" && !board && !error && (
        <div style={{ padding: 32, color: "var(--muted)" }}>Loading this week's board…</div>
      )}
      {tab === "board" && board && <Board data={board} inSlip={inSlip} onAdd={addLeg} />}

      {tab === "lines" && linesError && (
        <div style={{ padding: 32, color: "var(--neg)" }}>Couldn't reach the API: {linesError}</div>
      )}
      {tab === "lines" && !lines && !linesError && (
        <div style={{ padding: 32, color: "var(--muted)" }}>Loading this week's lines…</div>
      )}
      {tab === "lines" && lines && <Lines data={lines} />}

      {tab === "builder" && (
        <Builder slip={slip} onRemove={removeLeg} onGoBoard={() => setTab("board")} />
      )}
    </div>
  );
}
