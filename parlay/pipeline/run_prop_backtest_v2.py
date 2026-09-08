"""Prop Backtest v2: Team-specific context + Log-normal efficiency

Changes from v1:
  Fix 1: Uses each team's rolling play count and pass rate instead of
         league averages. A player on a run-heavy 55-play team now gets
         fewer simulated opportunities than one on a pass-heavy 70-play team.
  Fix 2: Log-normal distribution for efficiency draws instead of clipped
         normal. Eliminates the upward bias from max(0, ...) clipping
         and better matches the right-skewed shape of real yardage data.
"""

import json
from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import polars as pl
from scipy.special import expit

# ══════════════════════════════════════════════════════════════
# CONSTANTS AND PATHS
# ══════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent / "data"
SQL_DIR = Path(__file__).parent / "sql"
ODDS_DIR = DATA_DIR / "odds_historical"
DB_PATH = DATA_DIR / "nfl_data.duckdb"

LEAGUE_AVG_PLAYS = 62.3
PLAYS_SPREAD = 8.5
DEFAULT_PASS_RATE = 0.58

RESIDUAL_SPREADS = {
    "player_pass_yds": 2.63,
    "player_rush_yds": 2.67,
    "player_reception_yds": 6.01,
}

MARKET_TO_METRIC = {
    "player_pass_yds": "yards_per_attempt",
    "player_rush_yds": "yards_per_carry",
    "player_reception_yds": "yards_per_target",
}

MARKET_TO_STAT = {
    "player_pass_yds": "passing_yards",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
}

TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Rams": "LA", "Los Angeles Chargers": "LAC",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# ══════════════════════════════════════════════════════════════
# STEP 1: PARSE HISTORICAL PROP ODDS
# ══════════════════════════════════════════════════════════════

def parse_all_odds():
    rows = []
    for path in sorted(ODDS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        event_info = data.get("event_info", {})
        odds_data = data.get("odds_data", {})

        event_id = event_info.get("id", "")
        home_team = event_info.get("home_team", "")
        away_team = event_info.get("away_team", "")
        commence = event_info.get("commence_time", "")

        bookmakers = []
        if isinstance(odds_data, dict):
            if "data" in odds_data:
                inner = odds_data["data"]
                if isinstance(inner, dict):
                    bookmakers = inner.get("bookmakers", [])
                elif isinstance(inner, list):
                    for item in inner:
                        bookmakers.extend(item.get("bookmakers", []))
            else:
                bookmakers = odds_data.get("bookmakers", [])

        for book in bookmakers:
            for market in book.get("markets", []):
                market_key = market.get("key", "")
                if market_key not in MARKET_TO_STAT:
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "event_id": event_id,
                        "commence_time": commence,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker": book.get("key", ""),
                        "market": market_key,
                        "player": outcome.get("description", ""),
                        "side": outcome.get("name", ""),
                        "line": outcome.get("point"),
                        "price": outcome.get("price"),
                    })
    return pl.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
# STEP 2: DE-VIG AND CONSENSUS
# ══════════════════════════════════════════════════════════════

def american_to_prob(price):
    if price > 0:
        return 100 / (price + 100)
    return -price / (-price + 100)


def devig_and_consensus(odds_df):
    odds_df = odds_df.with_columns(
        pl.col("price").map_elements(
            lambda p: american_to_prob(p) if p is not None else None,
            return_dtype=pl.Float64
        ).alias("implied_prob")
    )

    devigged_rows = []
    groups = odds_df.group_by(["event_id", "bookmaker", "market", "player", "line"])

    for group_keys, group_df in groups:
        over_rows = group_df.filter(pl.col("side") == "Over")
        under_rows = group_df.filter(pl.col("side") == "Under")

        if over_rows.height == 0 or under_rows.height == 0:
            continue

        over_prob = over_rows["implied_prob"][0]
        under_prob = under_rows["implied_prob"][0]

        if over_prob is None or under_prob is None:
            continue

        total = over_prob + under_prob
        if total <= 0:
            continue

        fair_over = over_prob / total

        devigged_rows.append({
            "event_id": group_keys[0],
            "bookmaker": group_keys[1],
            "market": group_keys[2],
            "player": group_keys[3],
            "line": group_keys[4],
            "home_team": over_rows["home_team"][0],
            "away_team": over_rows["away_team"][0],
            "commence_time": over_rows["commence_time"][0],
            "fair_over_prob": fair_over,
        })

    if not devigged_rows:
        return pl.DataFrame()

    devigged_df = pl.DataFrame(devigged_rows)

    consensus = (
        devigged_df
        .group_by(["event_id", "market", "player", "line", "home_team", "away_team", "commence_time"])
        .agg([
            pl.col("fair_over_prob").median().alias("consensus_over_prob"),
            pl.col("fair_over_prob").count().alias("n_books"),
        ])
    )
    return consensus


# ══════════════════════════════════════════════════════════════
# STEP 3: ACTUAL GAME RESULTS
# ══════════════════════════════════════════════════════════════

def load_actual_stats():
    connection = duckdb.connect(str(DB_PATH), read_only=True)

    passing = connection.execute("""
        SELECT p.display_name AS player, pbp.game_id, s.home_team, s.away_team,
               'passing_yards' AS stat_type, COALESCE(SUM(pbp.passing_yards), 0) AS actual_yards
        FROM pbp_data pbp
        JOIN players_data p ON pbp.passer_player_id = p.gsis_id
        JOIN schedule_data s ON pbp.game_id = s.game_id
        WHERE pbp.play_type = 'pass' AND pbp.passer_player_id IS NOT NULL AND pbp.season >= 2025
        GROUP BY p.display_name, pbp.game_id, s.home_team, s.away_team
    """).pl()

    rushing = connection.execute("""
        SELECT p.display_name AS player, pbp.game_id, s.home_team, s.away_team,
               'rushing_yards' AS stat_type, COALESCE(SUM(pbp.rushing_yards), 0) AS actual_yards
        FROM pbp_data pbp
        JOIN players_data p ON pbp.rusher_player_id = p.gsis_id
        JOIN schedule_data s ON pbp.game_id = s.game_id
        WHERE pbp.play_type = 'run' AND pbp.rusher_player_id IS NOT NULL AND pbp.season >= 2025
        GROUP BY p.display_name, pbp.game_id, s.home_team, s.away_team
    """).pl()

    receiving = connection.execute("""
        SELECT p.display_name AS player, pbp.game_id, s.home_team, s.away_team,
               'receiving_yards' AS stat_type, COALESCE(SUM(pbp.receiving_yards), 0) AS actual_yards
        FROM pbp_data pbp
        JOIN players_data p ON pbp.receiver_player_id = p.gsis_id
        JOIN schedule_data s ON pbp.game_id = s.game_id
        WHERE pbp.play_type = 'pass' AND pbp.receiver_player_id IS NOT NULL AND pbp.season >= 2025
        GROUP BY p.display_name, pbp.game_id, s.home_team, s.away_team
    """).pl()

    connection.close()
    actual = pl.concat([passing, rushing, receiving])
    print(f"  Actual stats loaded: {actual.shape[0]} rows")
    return actual


# ══════════════════════════════════════════════════════════════
# STEP 4: LOAD MODELS
# ══════════════════════════════════════════════════════════════

def load_models():
    trace_path = DATA_DIR / "traces" / "target_share_trace_backtest.nc"
    if not trace_path.exists():
        trace_path = DATA_DIR / "traces" / "target_share_trace.nc"
        print("  Warning: using full trace, not backtest trace")

    ts_trace = az.from_netcdf(str(trace_path))

    connection = duckdb.connect(str(DB_PATH), read_only=True)

    # Target share index (filtered to training seasons)
    ts_result = connection.execute(Path(SQL_DIR / "target_share.sql").read_text()).pl()
    ts_result = ts_result.filter(pl.col("season") <= 2024)
    ts_result = ts_result.with_columns(
        (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
    )
    ts_unique = ts_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
    ts_names = ts_result.select(["gsis_id", "display_name"]).unique()
    ts_indexed = ts_unique.join(ts_names, on="gsis_id")
    ts_name_to_idx = {r["display_name"]: r["idx"] for r in ts_indexed.iter_rows(named=True)}
    ts_draws = expit(ts_trace.posterior["player_mu"].values.reshape(
        -1, ts_trace.posterior["player_mu"].shape[-1]))

    # Carry share index
    cs_trace = az.from_netcdf(str(DATA_DIR / "traces" / "carry_share_trace.nc"))
    cs_result = connection.execute(Path(SQL_DIR / "carry_share.sql").read_text()).pl()
    cs_result = cs_result.filter(pl.col("season") <= 2024)
    cs_result = cs_result.with_columns(
        (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
    )
    cs_unique = cs_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
    cs_names = cs_result.select(["gsis_id", "display_name"]).unique()
    cs_indexed = cs_unique.join(cs_names, on="gsis_id")
    cs_name_to_idx = {r["display_name"]: r["idx"] for r in cs_indexed.iter_rows(named=True)}
    cs_draws = expit(cs_trace.posterior["player_mu"].values.reshape(
        -1, cs_trace.posterior["player_mu"].shape[-1]))

    connection.close()

    # Efficiency estimates
    eff_df = pl.read_parquet(DATA_DIR / "player_efficiency_shrunk.parquet")
    eff_lookup = {}
    for row in eff_df.iter_rows(named=True):
        eff_lookup[(row["display_name"], row["metric"])] = row["shrunk_avg"]

    pos_avgs = {}
    for row in eff_df.group_by(["metric", "position_group"]).agg(
        pl.col("shrunk_avg").mean().alias("avg")
    ).iter_rows(named=True):
        pos_avgs[(row["position_group"], row["metric"])] = row["avg"]

    return {
        "ts_draws": ts_draws, "ts_idx": ts_name_to_idx,
        "cs_draws": cs_draws, "cs_idx": cs_name_to_idx,
        "eff_lookup": eff_lookup, "pos_avgs": pos_avgs,
    }


# ══════════════════════════════════════════════════════════════
# STEP 4b: LOAD TEAM-SPECIFIC CONTEXT (FIX 1)
# Each team's rolling play count and pass rate, so players
# on run-heavy teams get fewer simulated pass attempts than
# players on pass-heavy teams.
# ══════════════════════════════════════════════════════════════

def load_team_context():
    connection = duckdb.connect(str(DB_PATH), read_only=True)

    # Compute per-team per-game play count and pass rate,
    # then rolling average of prior games within the season
    raw = connection.execute("""
        SELECT
            posteam AS team,
            game_id,
            season,
            week,
            COUNT(*) AS game_plays,
            ROUND(SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS game_pass_rate
        FROM pbp_data
        WHERE play_type IN ('pass', 'run') AND posteam IS NOT NULL
        GROUP BY posteam, game_id, season, week
        ORDER BY posteam, season, week
    """).pl()

    connection.close()

    # Compute rolling averages using Polars (prior games only)
    raw = raw.sort(["team", "season", "week"])

    raw = raw.with_columns([
        pl.col("game_plays")
          .shift(1)
          .rolling_mean(window_size=100, min_periods=1)
          .over(["team", "season"])
          .alias("rolling_plays"),
        pl.col("game_pass_rate")
          .shift(1)
          .rolling_mean(window_size=100, min_periods=1)
          .over(["team", "season"])
          .alias("rolling_pass_rate"),
    ])

    # Build lookup: (team_abbr, game_id) -> {plays, pass_rate}
    lookup = {}
    for row in raw.iter_rows(named=True):
        plays = row["rolling_plays"] if row["rolling_plays"] is not None else LEAGUE_AVG_PLAYS
        pr = row["rolling_pass_rate"] if row["rolling_pass_rate"] is not None else DEFAULT_PASS_RATE
        lookup[(row["team"], row["game_id"])] = {
            "plays": plays,
            "pass_rate": pr,
        }

    return lookup


# ══════════════════════════════════════════════════════════════
# STEP 5: SIMULATE PROP (with both fixes)
# Fix 1: team-specific plays and pass rate
# Fix 2: log-normal efficiency instead of clipped normal
# ══════════════════════════════════════════════════════════════

def simulate_prop(player_name, market, line, models, n_sims=5000, seed=42,
                  team_plays=LEAGUE_AVG_PLAYS, team_pass_rate=DEFAULT_PASS_RATE):
    """Simulate P(Over line) for a given player prop.

    Fix 1: Uses team-specific play count and pass rate.
    Fix 2: Log-normal efficiency draws (no clipping bias).
    """
    rng = np.random.default_rng(seed)
    metric = MARKET_TO_METRIC[market]
    residual_spread = RESIDUAL_SPREADS[market]

    # Get efficiency estimate
    eff_key = (player_name, metric)
    if eff_key in models["eff_lookup"]:
        shrunk_eff = models["eff_lookup"][eff_key]
    else:
        matching = [(k, v) for k, v in models["eff_lookup"].items() if k[1] == metric]
        if matching:
            shrunk_eff = np.mean([v for _, v in matching])
        else:
            return None

    if shrunk_eff <= 0:
        return None

    # FIX 2: Log-normal parameters from mean + spread
    # Log-normal naturally stays positive and matches the right-skewed
    # shape of real yardage data. No max(0, ...) clipping needed.
    var = residual_spread ** 2
    mu_ln = np.log(shrunk_eff ** 2 / np.sqrt(shrunk_eff ** 2 + var))
    sigma_ln = np.sqrt(np.log(1 + var / shrunk_eff ** 2))

    overs = 0

    for _ in range(n_sims):
        # FIX 1: Draw play count centered on THIS team's average
        plays = max(30, round(rng.normal(team_plays, PLAYS_SPREAD)))

        if market == "player_pass_yds":
            attempts = max(5, round(plays * team_pass_rate))
            eff = rng.lognormal(mu_ln, sigma_ln)
            stat = attempts * eff

        elif market == "player_reception_yds":
            if player_name not in models["ts_idx"]:
                return None
            idx = models["ts_idx"][player_name]
            draw_i = rng.integers(0, models["ts_draws"].shape[0])
            usage = models["ts_draws"][draw_i, idx]
            attempts = max(5, round(plays * team_pass_rate))
            targets = usage * attempts
            eff = rng.lognormal(mu_ln, sigma_ln)
            stat = targets * eff

        elif market == "player_rush_yds":
            if player_name not in models["cs_idx"]:
                return None
            idx = models["cs_idx"][player_name]
            draw_i = rng.integers(0, models["cs_draws"].shape[0])
            usage = models["cs_draws"][draw_i, idx]
            rush_rate = 1 - team_pass_rate
            attempts = max(5, round(plays * rush_rate))
            carries = usage * attempts
            eff = rng.lognormal(mu_ln, sigma_ln)
            stat = carries * eff

        if stat > line:
            overs += 1

    return overs / n_sims


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("PROP BACKTEST v2: Team Context + Log-Normal Efficiency")
    print("=" * 60)

    # ── Parse odds ──
    print("\nStep 1: Parsing historical prop odds...")
    odds_df = parse_all_odds()
    print(f"  Raw prop outcomes: {odds_df.shape[0]}")

    # ── De-vig and consensus ──
    print("\nStep 2: De-vigging and computing consensus...")
    consensus = devig_and_consensus(odds_df)
    print(f"  Consensus props: {consensus.shape[0]}")

    # ── Load actual results ──
    print("\nStep 3: Loading actual game results...")
    actual = load_actual_stats()

    # ── Load models ──
    print("\nStep 4: Loading player models...")
    models = load_models()
    print(f"  Target share: {models['ts_draws'].shape[1]} players")
    print(f"  Carry share: {models['cs_draws'].shape[1]} players")
    print(f"  Efficiency: {len(models['eff_lookup'])} pairs")

    # ── Load team context (FIX 1) ──
    print("\nStep 4b: Loading team-specific context...")
    team_context = load_team_context()
    print(f"  Team-game contexts: {len(team_context)}")

    # ── Match props to actual results ──
    print("\nStep 5: Matching props to actual results...")

    consensus = consensus.with_columns([
        pl.col("home_team").replace(TEAM_NAME_TO_ABBR).alias("home_abbr"),
        pl.col("away_team").replace(TEAM_NAME_TO_ABBR).alias("away_abbr"),
    ])

    connection = duckdb.connect(str(DB_PATH), read_only=True)
    schedule = connection.execute("""
        SELECT game_id, home_team, away_team, season
        FROM schedule_data WHERE season >= 2025
    """).pl()
    connection.close()

    # Build player -> team lookup from actual stats
    player_team_lookup = {}
    for row in actual.iter_rows(named=True):
        player_team_lookup[(row["player"], row["game_id"])] = {
            "home_team": row["home_team"],
            "away_team": row["away_team"],
        }

    results = []
    matched = 0
    unmatched = 0

    for row in consensus.iter_rows(named=True):
        player = row["player"]
        market = row["market"]
        line = row["line"]
        book_over_prob = row["consensus_over_prob"]
        n_books = row["n_books"]
        home_abbr = row["home_abbr"]
        away_abbr = row["away_abbr"]

        if line is None or book_over_prob is None:
            continue

        stat_type = MARKET_TO_STAT[market]

        game_match = schedule.filter(
            (pl.col("home_team") == home_abbr) &
            (pl.col("away_team") == away_abbr)
        )

        if game_match.height == 0:
            unmatched += 1
            continue

        game_id = game_match["game_id"][0]

        actual_match = actual.filter(
            (pl.col("player") == player) &
            (pl.col("game_id") == game_id) &
            (pl.col("stat_type") == stat_type)
        )

        if actual_match.height == 0:
            unmatched += 1
            continue

        actual_yards = actual_match["actual_yards"][0]
        actual_over = actual_yards > line
        matched += 1

        results.append({
            "player": player,
            "market": market,
            "line": line,
            "actual_yards": actual_yards,
            "actual_over": actual_over,
            "book_over_prob": round(book_over_prob, 4),
            "n_books": n_books,
            "game_id": game_id,
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
        })

    results_df = pl.DataFrame(results)
    print(f"  Matched: {matched}, Unmatched: {unmatched}")

    # ── Simulate each prop with team-specific context ──
    print(f"\nStep 6: Simulating {results_df.shape[0]} props...")

    sim_probs = []
    simulated = 0

    for i, row in enumerate(results_df.iter_rows(named=True)):
        # FIX 1: Look up team-specific context for this player
        game_teams = player_team_lookup.get((row["player"], row["game_id"]))
        prop_team_plays = LEAGUE_AVG_PLAYS
        prop_pass_rate = DEFAULT_PASS_RATE

        if game_teams:
            # Determine which team the player is on
            # Try both teams' contexts
            for team_abbr in [game_teams["home_team"], game_teams["away_team"]]:
                ctx = team_context.get((team_abbr, row["game_id"]))
                if ctx:
                    # Use the first team context we find
                    # (player is associated with one of these teams)
                    prop_team_plays = ctx["plays"]
                    prop_pass_rate = ctx["pass_rate"]
                    break

        sim_prob = simulate_prop(
            player_name=row["player"],
            market=row["market"],
            line=row["line"],
            models=models,
            n_sims=5000,
            seed=42 + i,
            team_plays=prop_team_plays,
            team_pass_rate=prop_pass_rate,
        )
        sim_probs.append(sim_prob)

        if sim_prob is not None:
            simulated += 1

        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1} props...")

    results_df = results_df.with_columns(pl.Series("sim_over_prob", sim_probs))
    results_with_sim = results_df.filter(pl.col("sim_over_prob").is_not_null())
    print(f"  Successfully simulated: {results_with_sim.shape[0]}")

    # ══════════════════════════════════════════════════════════
    # EVALUATIONS
    # ══════════════════════════════════════════════════════════

    bins = [(0.0, 0.3), (0.3, 0.4), (0.4, 0.45), (0.45, 0.5),
            (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 1.0)]

    # ── Book calibration ──
    print("\n" + "=" * 60)
    print("BOOK CALIBRATION")
    print("=" * 60)
    print(f"{'Bin':>12}  {'Count':>6}  {'Book Prob':>10}  {'Actual':>8}  {'Gap':>8}")
    print("-" * 52)

    for lo, hi in bins:
        bin_df = results_with_sim.filter(
            (pl.col("book_over_prob") >= lo) & (pl.col("book_over_prob") < hi)
        )
        if bin_df.height < 5:
            continue
        predicted = bin_df["book_over_prob"].mean()
        actual_rate = bin_df["actual_over"].mean()
        gap = actual_rate - predicted
        print(f"  [{lo:.2f}-{hi:.2f})  {bin_df.height:>6}  {predicted:>10.4f}  {actual_rate:>8.4f}  {gap:>+8.4f}")

    # ── Simulator calibration ──
    print("\n" + "=" * 60)
    print("SIMULATOR CALIBRATION")
    print("=" * 60)
    print(f"{'Bin':>12}  {'Count':>6}  {'Sim Prob':>10}  {'Actual':>8}  {'Gap':>8}")
    print("-" * 52)

    for lo, hi in bins:
        bin_df = results_with_sim.filter(
            (pl.col("sim_over_prob") >= lo) & (pl.col("sim_over_prob") < hi)
        )
        if bin_df.height < 5:
            continue
        predicted = bin_df["sim_over_prob"].mean()
        actual_rate = bin_df["actual_over"].mean()
        gap = actual_rate - predicted
        print(f"  [{lo:.2f}-{hi:.2f})  {bin_df.height:>6}  {predicted:>10.4f}  {actual_rate:>8.4f}  {gap:>+8.4f}")

    # ── Brier scores ──
    print("\n" + "=" * 60)
    print("BRIER SCORES (lower is better)")
    print("=" * 60)

    book_brier = ((results_with_sim["book_over_prob"] - results_with_sim["actual_over"].cast(pl.Float64)) ** 2).mean()
    sim_brier = ((results_with_sim["sim_over_prob"] - results_with_sim["actual_over"].cast(pl.Float64)) ** 2).mean()

    print(f"Book Brier:      {book_brier:.4f}")
    print(f"Simulator Brier: {sim_brier:.4f}")
    print(f"Difference:      {sim_brier - book_brier:+.4f}")

    # ── Edge accuracy ──
    print("\n" + "=" * 60)
    print("EDGE ACCURACY")
    print("=" * 60)

    results_with_sim = results_with_sim.with_columns(
        (pl.col("sim_over_prob") - pl.col("book_over_prob")).alias("edge")
    )

    for threshold in [0.03, 0.05, 0.10]:
        sim_over_edge = results_with_sim.filter(pl.col("edge") > threshold)
        if sim_over_edge.height > 0:
            sim_pred = sim_over_edge["sim_over_prob"].mean()
            book_pred = sim_over_edge["book_over_prob"].mean()
            actual_rate = sim_over_edge["actual_over"].mean()
            print(f"\n  Edge > {threshold}: {sim_over_edge.height} props")
            print(f"    Sim predicted:  {sim_pred:.4f}")
            print(f"    Book predicted: {book_pred:.4f}")
            print(f"    Actual rate:    {actual_rate:.4f}")
            print(f"    Closer to:      {'Simulator' if abs(actual_rate - sim_pred) < abs(actual_rate - book_pred) else 'Book'}")

    # ── Summary by market ──
    print("\n" + "=" * 60)
    print("SUMMARY BY MARKET")
    print("=" * 60)

    for market in ["player_pass_yds", "player_rush_yds", "player_reception_yds"]:
        mkt_df = results_with_sim.filter(pl.col("market") == market)
        if mkt_df.height == 0:
            continue
        book_b = ((mkt_df["book_over_prob"] - mkt_df["actual_over"].cast(pl.Float64)) ** 2).mean()
        sim_b = ((mkt_df["sim_over_prob"] - mkt_df["actual_over"].cast(pl.Float64)) ** 2).mean()
        print(f"\n  {market}: {mkt_df.height} props")
        print(f"    Book Brier:  {book_b:.4f}")
        print(f"    Sim Brier:   {sim_b:.4f}")
        print(f"    Difference:  {sim_b - book_b:+.4f}")

    # ── Compare v1 vs v2 ──
    print("\n" + "=" * 60)
    print("v1 vs v2 COMPARISON")
    print("=" * 60)
    print("                    v1 (league avg + clipped normal)")
    print("  pass_yds Brier:   +0.0131 vs book")
    print("  rush_yds Brier:   +0.0467 vs book")
    print("  recv_yds Brier:   +0.0164 vs book")
    print("\n                    v2 (team context + log-normal)")
    for market in ["player_pass_yds", "player_rush_yds", "player_reception_yds"]:
        mkt_df = results_with_sim.filter(pl.col("market") == market)
        if mkt_df.height == 0:
            continue
        book_b = ((mkt_df["book_over_prob"] - mkt_df["actual_over"].cast(pl.Float64)) ** 2).mean()
        sim_b = ((mkt_df["sim_over_prob"] - mkt_df["actual_over"].cast(pl.Float64)) ** 2).mean()
        label = market.replace("player_", "").replace("_", " ")
        print(f"  {label} Brier: {sim_b - book_b:+.4f} vs book")