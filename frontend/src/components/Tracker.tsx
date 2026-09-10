import { useEffect, useState } from "react";
import { fmtAmerican } from "../api";

export interface TrackedParlay {
  id: string;
  savedAt: string;
  stake: number;
  legLabels: string[];
  combinedPrice: number | null;
  fairPrice: number | null;
  edgePct: number | null;
  status: "pending" | "won" | "lost";
}

const STORAGE_KEY = "vig.trackedParlays";

function load(): TrackedParlay[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function save(parlays: TrackedParlay[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(parlays));
  } catch {
    // best-effort only -- private browsing / disabled storage just means no history
  }
}

const decProfit = (a: number) => (a > 0 ? a / 100 : 100 / -a);

export function useTracker() {
  const [parlays, setParlays] = useState<TrackedParlay[]>([]);

  useEffect(() => {
    setParlays(load());
  }, []);

  const add = (p: Omit<TrackedParlay, "id" | "savedAt" | "status">) => {
    const entry: TrackedParlay = {
      ...p,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      savedAt: new Date().toISOString(),
      status: "pending",
    };
    setParlays((prev) => {
      const next = [entry, ...prev];
      save(next);
      return next;
    });
  };

  const setStatus = (id: string, status: TrackedParlay["status"]) => {
    setParlays((prev) => {
      const next = prev.map((p) => (p.id === id ? { ...p, status } : p));
      save(next);
      return next;
    });
  };

  const remove = (id: string) => {
    setParlays((prev) => {
      const next = prev.filter((p) => p.id !== id);
      save(next);
      return next;
    });
  };

  return { parlays, add, setStatus, remove };
}

export default function Tracker({
  parlays,
  onSetStatus,
  onRemove,
}: {
  parlays: TrackedParlay[];
  onSetStatus: (id: string, status: TrackedParlay["status"]) => void;
  onRemove: (id: string) => void;
}) {
  const won = parlays.filter((p) => p.status === "won");
  const lost = parlays.filter((p) => p.status === "lost");
  const pending = parlays.filter((p) => p.status === "pending");
  const netUnits = parlays.reduce((sum, p) => {
    if (p.status === "won" && p.combinedPrice != null) return sum + p.stake * decProfit(p.combinedPrice);
    if (p.status === "lost") return sum - p.stake;
    return sum;
  }, 0);

  return (
    <div style={{ marginTop: 42, maxWidth: 680 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ fontSize: 13, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.9px" }}>
          Tracker
        </div>
        {parlays.length > 0 && (
          <div className="mono" style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {won.length}-{lost.length}-{pending.length} ·{" "}
            <span style={{ color: netUnits >= 0 ? "var(--green)" : "var(--neg)" }}>
              {netUnits >= 0 ? "+" : ""}${netUnits.toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {parlays.length === 0 && (
        <div style={{ color: "var(--faint)", fontSize: 13.5, marginTop: 10 }}>
          Saved parlays show up here — price a slip and hit "Save to tracker".
        </div>
      )}

      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
        {parlays.map((p) => (
          <div key={p.id} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                {p.legLabels.map((l, i) => (
                  <div key={i}>{l}</div>
                ))}
              </div>
              <button onClick={() => onRemove(p.id)} style={{ color: "var(--faint)", fontSize: 12 }}>
                ✕
              </button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
              <span className="mono" style={{ fontSize: 12.5, color: "var(--muted)" }}>
                ${p.stake} @ {fmtAmerican(p.combinedPrice)}
                {p.edgePct != null && (
                  <span style={{ color: p.edgePct >= 0 ? "var(--green)" : "var(--neg)" }}>
                    {" "}
                    ({p.edgePct >= 0 ? "+" : ""}
                    {p.edgePct}% edge)
                  </span>
                )}
              </span>
              <span style={{ flexGrow: 1 }} />
              {(["pending", "won", "lost"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => onSetStatus(p.id, s)}
                  style={{
                    padding: "4px 10px",
                    borderRadius: 6,
                    fontSize: 11.5,
                    textTransform: "uppercase",
                    letterSpacing: "0.4px",
                    border: p.status === s ? "none" : "1px solid var(--border)",
                    background:
                      p.status === s
                        ? s === "won"
                          ? "var(--greenSoft)"
                          : s === "lost"
                            ? "rgba(255,90,90,0.15)"
                            : "var(--panel)"
                        : "transparent",
                    color:
                      p.status === s
                        ? s === "won"
                          ? "var(--green)"
                          : s === "lost"
                            ? "var(--neg)"
                            : "var(--muted)"
                        : "var(--faint)",
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
