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
}

export interface GameLines {
  source: "live" | "sample";
  games: number;
  books: number;
  rows: GameLineRow[];
}

export interface Leg {
  player: string;
  market: string;
  line: number;
  side: "over" | "under";
  team: string | null;
  home: boolean;
}

export interface LegProb {
  player: string;
  market: string;
  line: number;
  side: "over" | "under";
  prob: number;
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
