"""Game-lines service: moneyline / spread / total, sibling of board.py.

Reads the ``devig_lines`` table written by parlay/pipeline/devig_lines.py.
Same shape of query as board.py's player-prop board, just partitioned by
(event, market, side, line) instead of (player, market, side, line) since
game lines have no player. Falls back to sample data if the warehouse or
table isn't present.
"""

from pathlib import Path

import duckdb

from parlay.api.sample_data import sample_lines

WAREHOUSE = Path(__file__).parent.parent / "data" / "nfl_data.duckdb"

MARKET_LABELS = {"h2h": "Moneyline", "spreads": "Spread", "totals": "Total"}


def get_lines():
    try:
        lines = _lines_from_warehouse()
        if lines and lines["rows"]:
            return lines
    except Exception:  # noqa: BLE001 -- any warehouse/query failure degrades to sample data
        return sample_lines()
    return sample_lines()


def _lines_from_warehouse():
    if not WAREHOUSE.exists():
        return None
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "devig_lines" not in tables:
            return None

        # Latest snapshot only; best (most +EV) book per game/market/side/line.
        rows = con.execute(
            """
            WITH latest AS (SELECT max(snapshot_ts) AS ts FROM devig_lines),
            ranked AS (
                SELECT d.*,
                       row_number() OVER (
                         PARTITION BY event_id, market, side, line
                         ORDER BY ev_per_dollar DESC
                       ) AS rn
                FROM devig_lines d, latest
                WHERE d.snapshot_ts = latest.ts
                  AND d.consensus_fair_prob IS NOT NULL
            )
            SELECT event_id, commence_time, home_team, away_team, market, line,
                   side, bookmaker, price, fair_price, consensus_fair_prob, ev_per_dollar
            FROM ranked
            WHERE rn = 1
            ORDER BY commence_time, event_id, market, side
            """
        ).fetchall()
        if not rows:
            return None

        out = []
        for (event_id, commence, home_team, away_team, market, line, side,
             book, price, fair_price, cons, ev) in rows:
            out.append({
                "id": f"{event_id}-{market}-{side}-{line}".replace(" ", "-").lower(),
                "event_id": event_id,
                "commence_time": commence,
                "home_team": home_team,
                "away_team": away_team,
                "market": market,
                "market_label": MARKET_LABELS.get(market, market),
                "line": line,
                "side": side,
                "book": book,
                "price": int(price) if price is not None else None,
                "fair_price": int(fair_price) if fair_price is not None else None,
                "consensus_prob": round(cons, 4) if cons is not None else None,
                "edge_pct": round((ev or 0) * 100, 1),
                "priceable": True,
            })

        games = len({r["event_id"] for r in out})
        books = len({r["book"] for r in out if r["book"]})
        return {"source": "live", "games": games, "books": books, "rows": out}
    finally:
        con.close()
