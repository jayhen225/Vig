export interface BoardRow {
  id: string;
  player: string;
  team: string | null;
  position: string | null;
  opponent: string | null;
  home: boolean | null;
  market: string;
  market_label: string;
  line: number;
  side: "over" | "under";
  book: string | null;
  price: number | null;
  fair_price: number | null;
  consensus_prob: number | null;
  edge_pct: number;
  priceable: boolean;
}

export interface Board {
  source: "live" | "sample";
  season: number | null;
  week: number | null;
  updated_minutes_ago: number | null;
  stats: {
    ev_count: number;
    avg_edge: number;
    games_live: number;
    games_total: number;
    books: number;
  };
  rows: BoardRow[];
}

export interface GameLineRow {
  id: string;
  event_id: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  market: "h2h" | "spreads" | "totals";
  market_label: string;
  line: number | null;
  side: string;
  book: string | null;
  price: number | null;
  fair_price: number | null;
  consensus_prob: number | null;
  edge_pct: number;
  priceable: boolean;
}

export interface GameLines {
  source: "live" | "sample";
  games: number;
  books: number;
  rows: GameLineRow[];
}

export interface Leg {
  player?: string | null;
  market: string;
  line?: number | null;
  side: string;
  team?: string | null;
  home?: boolean;
  home_team?: string | null;
  away_team?: string | null;
}

export interface LegProb {
  player: string | null;
  market: string;
  line: number | null;
  side: string;
  team: string | null;
  prob: number;
}

// A slip can mix player-prop rows (from the Edge Board) and game-line rows
// (from the Game Lines tab) -- tagged so the builder knows how to render
// each and how to shape it into a Leg for /api/price.
export type SlipLeg =
  | ({ kind: "prop" } & BoardRow)
  | ({ kind: "game_line" } & GameLineRow);

export function slipLegToApiLeg(l: SlipLeg): Leg {
  if (l.kind === "prop") {
    return { player: l.player, market: l.market, line: l.line, side: l.side, team: l.team, home: l.home ?? true };
  }
  const team = l.market === "totals" ? null : l.side;
  return {
    market: l.market, line: l.line, side: l.market === "totals" ? l.side.toLowerCase() : "over",
    team, home_team: l.home_team, away_team: l.away_team,
  };
}

export interface PriceResult {
  source: "live" | "estimate";
  correlated_prob: number;
  independent_prob: number;
  correlation_edge: number;
  fair_price: number | null;
  book_price: number | null;
  individual: LegProb[];
  market_labels: Record<string, string>;
}

export interface PriceError {
  error: string;
  message: string;
  unsupported: string[];
  priceable_markets: string[];
}

export async function getBoard(): Promise<Board> {
  const r = await fetch("/api/board");
  if (!r.ok) throw new Error(`board ${r.status}`);
  return r.json();
}

export async function getLines(): Promise<GameLines> {
  const r = await fetch("/api/lines");
  if (!r.ok) throw new Error(`lines ${r.status}`);
  return r.json();
}

export async function priceParlay(legs: Leg[]): Promise<PriceResult | PriceError> {
  const r = await fetch("/api/price", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ legs }),
  });
  if (!r.ok) throw new Error(`price ${r.status}`);
  return r.json();
}

export const fmtAmerican = (n: number | null): string =>
  n == null ? "—" : n > 0 ? `+${n}` : `${n}`;

export const fmtPct = (p: number): string => `${(p * 100).toFixed(1)}%`;
