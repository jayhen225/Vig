"""Edge board service.

Reads this week's de-vigged props from the DuckDB warehouse (the ``devig_odds``
table written by parlay/pipeline/devig_odds.py), reduces to the best +EV book per
outcome, and shapes them for the frontend. If the warehouse or table isn't
present, returns sample data (flagged) so the UI still runs.

The team join is best-effort against whatever roster table exists; refine the SQL
against the real warehouse. Any failure falls back to sample data.
"""

from pathlib import Path

import duckdb

from parlay.api.sample_data import MARKET_LABELS, PRICEABLE_MARKETS, sample_board

WAREHOUSE = Path(__file__).parent.parent / "data" / "nfl_data.duckdb"


def get_board():
    try:
        board = _board_from_warehouse()
        if board and board["rows"]:
            return board
    except Exception:  # noqa: BLE001 -- any warehouse/query failure degrades to sample data
        return sample_board()
    return sample_board()


def _board_from_warehouse():
    if not WAREHOUSE.exists():
        return None
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "devig_odds" not in tables:
            return None

        markets = tuple(PRICEABLE_MARKETS) or ("",)
        # Latest snapshot only; one row per player/market/side. Books quote
        # slightly different lines for the same prop (e.g. a QB's pass-yards
        # Over at 215.5 from one book, 224.5 from another) -- partitioning
        # further by line as well would surface each book's own line as a
        # separate "opportunity", flooding the board with near-duplicate rows
        # for a few players while everyone else's props get crowded out of
        # the LIMIT. Rank by n_books (how many books agree on that specific
        # line -- a real consensus, not a single book's quote against itself)
        # before ev_per_dollar, so the board picks the most-agreed-on line.
        rows = con.execute(
            """
            WITH latest AS (SELECT max(snapshot_ts) AS ts FROM devig_odds),
            ranked AS (
                SELECT d.*,
                       row_number() OVER (
                         PARTITION BY player, market, side
                         ORDER BY n_books DESC, ev_per_dollar DESC
                       ) AS rn
                FROM devig_odds d, latest
                WHERE d.snapshot_ts = latest.ts
                  AND d.consensus_fair_prob IS NOT NULL
                  AND d.market IN ?
            )
            SELECT player, market, line, side, bookmaker, price, fair_price,
                   consensus_fair_prob, ev_per_dollar, home_team, away_team
            FROM ranked
            WHERE rn = 1
            ORDER BY ev_per_dollar DESC
            LIMIT 150
            """,
            [list(markets)],
        ).fetchall()
        if not rows:
            return None

        out = []
        for (player, market, line, side, book, price, fair_price,
             cons, ev, home_team, away_team) in rows:
            out.append({
                "id": f"{player}-{market}-{side}".replace(" ", "-").lower(),
                "player": player,
                "team": None,  # refine: join roster on player -> team abbrev
                "position": None,
                "opponent": f"{away_team} @ {home_team}" if home_team else None,
                "home": None,
                "market": market,
                "market_label": MARKET_LABELS.get(market, market),
                "line": line,
                # Raw side from the odds API is title-case ("Over"/"Under");
                # normalize once here so the frontend's "over"/"under" checks
                # and the pricer's leg resolution (which also compares against
                # lowercase) both work against live data, not just sample data.
                "side": side.lower() if side else side,
                "book": book,
                "price": int(price) if price is not None else None,
                "fair_price": int(fair_price) if fair_price is not None else None,
                "consensus_prob": round(cons, 4) if cons is not None else None,
                "edge_pct": round((ev or 0) * 100, 1),
                "priceable": market in PRICEABLE_MARKETS,
            })

        ev_rows = [r for r in out if r["edge_pct"] > 0]
        avg = round(sum(r["edge_pct"] for r in ev_rows) / len(ev_rows), 1) if ev_rows else 0.0
        games = len({r["opponent"] for r in out if r["opponent"]})
        books = len({r["book"] for r in out if r["book"]})
        return {
            "source": "live",
            "season": None,
            "week": None,
            "updated_minutes_ago": None,
            "stats": {"ev_count": len(ev_rows), "avg_edge": avg,
                      "games_live": games, "games_total": games, "books": books},
            "rows": out,
        }
    finally:
        con.close()
