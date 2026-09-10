import { Chevron, Logo } from "./icons";

type Tab = "board" | "lines" | "builder";

export default function TopBar({
  tab,
  onTab,
  slipCount,
  week,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  slipCount: number;
  week: string;
}) {
  return (
    <div
      style={{
        height: 66,
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 36,
        padding: "0 32px",
        borderBottom: "1px solid var(--hair)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <Logo />
        <span style={{ fontFamily: "var(--mono)", fontWeight: 600, fontSize: 19, letterSpacing: 2 }}>
          VIG
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
        <button className={`tab ${tab === "board" ? "active" : ""}`} onClick={() => onTab("board")}>
          Edge Board
        </button>
        <button className={`tab ${tab === "lines" ? "active" : ""}`} onClick={() => onTab("lines")}>
          Game Lines
        </button>
        <button className={`tab ${tab === "builder" ? "active" : ""}`} onClick={() => onTab("builder")}>
          Parlay Builder
          {slipCount > 0 && (
            <span
              style={{
                marginLeft: 8,
                fontFamily: "var(--mono)",
                fontSize: 12,
                color: "#08130c",
                background: "var(--green)",
                borderRadius: 20,
                padding: "1px 7px",
              }}
            >
              {slipCount}
            </span>
          )}
        </button>
      </div>
      <div style={{ flexGrow: 1 }} />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 14px",
          border: "1px solid var(--border)",
          borderRadius: 9,
          fontFamily: "var(--mono)",
          fontSize: 13,
        }}
      >
        {week}
        <Chevron />
      </div>
    </div>
  );
}
