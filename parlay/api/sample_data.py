"""Sample board + parlay data.

Used as a fallback so the API (and the frontend) run even when the trained
models, warehouse, and de-vig output are not present on this machine. Every
response built from this data is flagged ``source: "sample"`` so the UI can say
so plainly. The numbers mirror the design mock-ups.
"""

MARKET_LABELS = {
    "player_pass_yds": "Pass Yds",
    "player_rush_yds": "Rush Yds",
    "player_reception_yds": "Rec Yds",
}

# Markets the correlation pricer supports (others show on the board but can't be
# added to a priced parlay).
PRICEABLE_MARKETS = set(MARKET_LABELS)

SAMPLE_WEEK = {"season": 2026, "week": 1, "updated_minutes_ago": 14}

# One row per (player, market) — the shape /api/board returns.
SAMPLE_BOARD = [
    {"id": "kelce-rec", "player": "Travis Kelce", "team": "KC", "position": "TE",
     "opponent": "BAL", "home": True, "market": "player_reception_yds", "line": 65.5,
     "side": "over", "book": "FanDuel", "price": 100, "fair_price": -108,
     "consensus_prob": 0.519, "edge_pct": 5.1},
    {"id": "barkley-rush", "player": "Saquon Barkley", "team": "PHI", "position": "RB",
     "opponent": "DAL", "home": True, "market": "player_rush_yds", "line": 82.5,
     "side": "over", "book": "BetMGM", "price": -110, "fair_price": -128,
     "consensus_prob": 0.561, "edge_pct": 4.6},
    {"id": "mahomes-pass", "player": "Patrick Mahomes", "team": "KC", "position": "QB",
     "opponent": "BAL", "home": True, "market": "player_pass_yds", "line": 275.5,
     "side": "over", "book": "DraftKings", "price": -115, "fair_price": -104,
     "consensus_prob": 0.510, "edge_pct": 3.8},
    {"id": "chase-rec", "player": "Ja'Marr Chase", "team": "CIN", "position": "WR",
     "opponent": "NE", "home": True, "market": "player_reception_yds", "line": 88.5,
     "side": "over", "book": "DraftKings", "price": -110, "fair_price": -124,
     "consensus_prob": 0.553, "edge_pct": 3.5},
    {"id": "bijan-rush", "player": "Bijan Robinson", "team": "ATL", "position": "RB",
     "opponent": "CAR", "home": True, "market": "player_rush_yds", "line": 74.5,
     "side": "over", "book": "Caesars", "price": -105, "fair_price": -118,
     "consensus_prob": 0.541, "edge_pct": 3.1},
    {"id": "jefferson-rec", "player": "Justin Jefferson", "team": "MIN", "position": "WR",
     "opponent": "CHI", "home": False, "market": "player_reception_yds", "line": 79.5,
     "side": "over", "book": "FanDuel", "price": -112, "fair_price": -122,
     "consensus_prob": 0.549, "edge_pct": 2.4},
    {"id": "allen-pass", "player": "Josh Allen", "team": "BUF", "position": "QB",
     "opponent": "ARI", "home": True, "market": "player_pass_yds", "line": 251.5,
     "side": "over", "book": "BetMGM", "price": -108, "fair_price": -116,
     "consensus_prob": 0.537, "edge_pct": 2.2},
    {"id": "henry-rush", "player": "Derrick Henry", "team": "BAL", "position": "RB",
     "opponent": "KC", "home": False, "market": "player_rush_yds", "line": 85.5,
     "side": "under", "book": "DraftKings", "price": -115, "fair_price": -112,
     "consensus_prob": 0.528, "edge_pct": -0.6},
]


LINE_MARKET_LABELS = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}

# One row per (game, market, side) -- the shape /api/lines returns.
SAMPLE_LINES = [
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "h2h", "line": None, "side": "Kansas City Chiefs",
     "book": "DraftKings", "price": 124, "fair_price": 130,
     "consensus_prob": 0.435, "edge_pct": 2.6},
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "h2h", "line": None, "side": "Baltimore Ravens",
     "book": "FanDuel", "price": -142, "fair_price": -150,
     "consensus_prob": 0.596, "edge_pct": 1.9},
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "spreads", "line": 3.0, "side": "Baltimore Ravens",
     "book": "BetMGM", "price": -108, "fair_price": -112,
     "consensus_prob": 0.522, "edge_pct": 1.1},
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "spreads", "line": -3.0, "side": "Kansas City Chiefs",
     "book": "Caesars", "price": -105, "fair_price": -112,
     "consensus_prob": 0.522, "edge_pct": 2.2},
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "totals", "line": 47.5, "side": "Over",
     "book": "DraftKings", "price": -108, "fair_price": -110,
     "consensus_prob": 0.524, "edge_pct": 0.6},
    {"event_id": "sample-kc-bal", "commence_time": "2026-09-14T17:00:00Z",
     "home_team": "Baltimore Ravens", "away_team": "Kansas City Chiefs",
     "market": "totals", "line": 47.5, "side": "Under",
     "book": "BetMGM", "price": -105, "fair_price": -110,
     "consensus_prob": 0.524, "edge_pct": 1.7},
]


def sample_lines():
    rows = [{**r, "market_label": LINE_MARKET_LABELS.get(r["market"], r["market"])}
            for r in SAMPLE_LINES]
    games = len({r["event_id"] for r in rows})
    books = len({r["book"] for r in rows})
    return {"source": "sample", "games": games, "books": books, "rows": rows}


def sample_board():
    ev = [r for r in SAMPLE_BOARD if r["edge_pct"] > 0]
    avg = round(sum(r["edge_pct"] for r in ev) / len(ev), 1) if ev else 0.0
    rows = [{**r, "market_label": MARKET_LABELS.get(r["market"], r["market"]),
             "priceable": r["market"] in PRICEABLE_MARKETS} for r in SAMPLE_BOARD]
    return {
        "source": "sample",
        "season": SAMPLE_WEEK["season"],
        "week": SAMPLE_WEEK["week"],
        "updated_minutes_ago": SAMPLE_WEEK["updated_minutes_ago"],
        "stats": {"ev_count": len(ev), "avg_edge": avg, "games_live": 14,
                  "games_total": 16, "books": 4},
        "rows": rows,
    }
