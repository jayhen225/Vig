"""De-vig a captured odds snapshot into fair probabilities, consensus, and +EV flags.

Reads the latest raw snapshot written by pipeline/snapshot_odds.py
(data/odds_raw/<timestamp>/*.json), and for every player-prop outcome produces:
  * book_fair_prob      -- per-book de-vigged probability (2-sided markets only)
  * consensus_fair_prob -- cross-book consensus (median of book fair probs)
  * ev_per_dollar / is_positive_ev -- each book's price vs the consensus fair prob

Output is written to data/odds_devig/<timestamp>.parquet and (re)loaded into the
`devig_odds` table of the DuckDB warehouse, keeping the full snapshot time series.
"""

import json
import sys
from pathlib import Path

import duckdb
import polars as pl

from parlay.core.devig import (
    american_to_prob,
    consensus_prob,
    devig,
    expected_value,
    is_positive_ev,
    prob_to_american,
)

DATA_DIR = Path(__file__).parent.parent / "data"
ODDS_RAW = DATA_DIR / "odds_raw"
ODDS_DEVIG = DATA_DIR / "odds_devig"
WAREHOUSE = DATA_DIR / "nfl_data.duckdb"


def latest_snapshot(root=ODDS_RAW):
    """Return the most recent snapshot directory, or None if there are none."""
    if not root.exists():
        return None
    dirs = [d for d in root.iterdir() if d.is_dir()]
    return max(dirs, key=lambda d: d.name) if dirs else None


def flatten_event(event, snapshot_ts):
    """Flatten one event's bookmakers -> markets -> outcomes into a list of rows."""
    rows = []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            for outcome in market.get("outcomes", []):
                rows.append(
                    {
                        "snapshot_ts": snapshot_ts,
                        "event_id": event.get("id"),
                        "commence_time": event.get("commence_time"),
                        "home_team": event.get("home_team"),
                        "away_team": event.get("away_team"),
                        "bookmaker": book.get("key"),
                        "market": market.get("key"),
                        "player": outcome.get("description"),
                        "line": outcome.get("point"),
                        "side": outcome.get("name"),
                        "price": outcome.get("price"),
                    }
                )
    return rows


def parse_snapshot(snapshot_dir):
    """Read every event file in a snapshot directory into flat outcome rows."""
    rows = []
    for path in sorted(snapshot_dir.glob("*.json")):
        if path.name == "events.json":
            continue
        rows.extend(flatten_event(json.loads(path.read_text()), snapshot_dir.name))
    return rows


def devig_rows(rows, method="multiplicative", consensus_method="median", ev_threshold=0.0):
    """Add book_fair_prob, consensus_fair_prob, fair_price and EV fields to rows.

    Mutates and returns ``rows`` (a list of dicts from ``flatten_event``).
    """
    for row in rows:
        price = row["price"]
        row["book_implied_prob"] = american_to_prob(price) if price is not None else None
        row["book_fair_prob"] = None

    # De-vig per book: only complete 2-sided markets (Over/Under or Yes/No).
    market_groups = _group_by(rows, ("event_id", "bookmaker", "market", "player", "line"))
    for idxs in market_groups.values():
        probs = [rows[i]["book_implied_prob"] for i in idxs]
        if len(idxs) == 2 and all(p is not None for p in probs):
            for i, fair in zip(idxs, devig(probs, method=method)):
                rows[i]["book_fair_prob"] = fair
        # One-sided / incomplete markets (e.g. anytime_td with no "No") stay None.

    # Consensus across books for each distinct outcome.
    outcome_groups = _group_by(rows, ("event_id", "market", "player", "line", "side"))
    for idxs in outcome_groups.values():
        fair_probs = [rows[i]["book_fair_prob"] for i in idxs if rows[i]["book_fair_prob"] is not None]
        consensus = consensus_prob(fair_probs, method=consensus_method) if fair_probs else None
        for i in idxs:
            rows[i]["consensus_fair_prob"] = consensus
            rows[i]["n_books"] = len(fair_probs)
            rows[i]["fair_price"] = (
                prob_to_american(consensus) if consensus is not None and 0 < consensus < 1 else None
            )

    # EV of each book's actual price against the consensus fair probability.
    for row in rows:
        consensus = row.get("consensus_fair_prob")
        if consensus is not None and row["price"] is not None:
            row["ev_per_dollar"] = expected_value(row["price"], consensus)
            row["is_positive_ev"] = bool(is_positive_ev(row["price"], consensus, ev_threshold))
        else:
            row["ev_per_dollar"] = None
            row["is_positive_ev"] = None
    return rows


def _group_by(rows, keys):
    """Map each distinct tuple of ``keys`` to the list of row indices sharing it."""
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(tuple(row[k] for k in keys), []).append(i)
    return groups


def main():
    snapshot = latest_snapshot()
    if snapshot is None:
        sys.exit(f"No snapshots in {ODDS_RAW}. Run pipeline/snapshot_odds.py first.")

    rows = parse_snapshot(snapshot)
    if not rows:
        sys.exit(f"No outcomes parsed from {snapshot}.")
    devig_rows(rows)

    ODDS_DEVIG.mkdir(parents=True, exist_ok=True)
    out_path = ODDS_DEVIG / f"{snapshot.name}.parquet"
    pl.DataFrame(rows).write_parquet(out_path)
    print(f"Wrote {len(rows)} rows to {out_path}")

    connection = duckdb.connect(WAREHOUSE)
    connection.execute(
        f"CREATE OR REPLACE TABLE devig_odds AS "
        f"SELECT * FROM read_parquet('{ODDS_DEVIG.as_posix()}/*.parquet')"
    )
    total = connection.execute("SELECT count(*) FROM devig_odds").fetchone()[0]
    positive = connection.execute(
        "SELECT count(*) FROM devig_odds WHERE is_positive_ev"
    ).fetchone()[0]
    connection.close()
    print(f"devig_odds table: {total} rows across all snapshots, {positive} positive-EV.")


if __name__ == "__main__":
    main()
