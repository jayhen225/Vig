"""Devig the latest game-line snapshot (moneyline/spread/total) into the warehouse.

Sibling of devig_odds.py, which handles player props -- reuses the same devig
logic (parlay/core/devig.py's math is market-shape-agnostic: h2h and totals are
2-sided just like an Over/Under prop, spreads are 2-sided per line) via
devig_odds.run(), just pointed at the game-lines snapshot root and a separate
`devig_lines` table so the two capture cadences (weekly cheap vs. on-demand
expensive player props) don't collide in one table.
"""

from parlay.pipeline.devig_odds import DATA_DIR, run

SNAPSHOT_ROOT = DATA_DIR / "odds_raw_lines"
ODDS_DEVIG = DATA_DIR / "odds_devig_lines"


def main():
    run(SNAPSHOT_ROOT, ODDS_DEVIG, "devig_lines")


if __name__ == "__main__":
    main()
