"""Backtest v2: Team-specific EPA + Home-Field Advantage

Changes from v1:
  - Loads rolling offensive EPA per team per game from team_game_features.sql
  - Adds home-field advantage (1.6 points, converted to ~0.026 EPA/play bump)
  - Falls back to league average for week 1 or missing data (same as v1)
"""

from pathlib import Path

import duckdb
import numpy as np
import polars as pl

# ══════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════
LEAGUE_AVG_POINTS = 22.92
LEAGUE_AVG_PLAYS = 62.3
PLAYS_SPREAD = 8.5
LEAGUE_AVG_DEF_EPA = 0.0024
DEF_EPA_SPREAD = 0.2170
OFF_EPA_SPREAD = 0.2091
DEFAULT_PASS_RATE = 0.58

# Home-field advantage: 1.6 points / ~62 plays ≈ 0.026 EPA/play
HOME_EPA_BUMP = 0.026

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
    "Las Vegas Raiders": "LV", "Oakland Raiders": "OAK",
    "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO",
    "New York Giants": "NYG", "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

# ══════════════════════════════════════════════════════════════
# SIMULATION (same as v1, unchanged)
# ══════════════════════════════════════════════════════════════

def simulate_game_scores(rng, home_epa=0.0, away_epa=0.0):
    home_off = rng.normal(loc=home_epa, scale=OFF_EPA_SPREAD)
    away_def = rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=DEF_EPA_SPREAD)
    home_matchup = home_off + away_def
    home_plays = max(30, round(rng.normal(loc=LEAGUE_AVG_PLAYS, scale=PLAYS_SPREAD)))
    home_points = max(0, round(LEAGUE_AVG_POINTS + (home_matchup * home_plays)))

    away_off = rng.normal(loc=away_epa, scale=OFF_EPA_SPREAD)
    home_def = rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=DEF_EPA_SPREAD)
    away_matchup = away_off + home_def
    away_plays = max(30, round(rng.normal(loc=LEAGUE_AVG_PLAYS, scale=PLAYS_SPREAD)))
    away_points = max(0, round(LEAGUE_AVG_POINTS + (away_matchup * away_plays)))

    return home_points, away_points


def simulate_game_probabilities(n_sims, spread, home_epa=0.0, away_epa=0.0, seed=42):
    rng = np.random.default_rng(seed)
    spread_covers = 0
    home_wins = 0

    for _ in range(n_sims):
        home_score, away_score = simulate_game_scores(rng, home_epa, away_epa)
        margin = home_score - away_score

        if margin + spread > 0:
            spread_covers += 1
        if home_score > away_score:
            home_wins += 1

    return {
        "p_home_covers": spread_covers / n_sims,
        "p_home_wins": home_wins / n_sims,
    }


# ══════════════════════════════════════════════════════════════
# LOAD ROLLING EPA FEATURES
# These were computed by team_game_features.sql with
# leakage-free rolling windows (prior games only).
# ══════════════════════════════════════════════════════════════

print("Loading rolling EPA features...")
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "team_game_features.sql"
features_df = connection.execute(sql_path.read_text()).pl()
connection.close()

# Filter to 2025 season
features_2025 = features_df.filter(pl.col("season") >= 2025)

# Build lookup: (team_abbr, season, week) -> rolling_off_epa
# This lets us quickly find each team's rolling EPA heading into any game
rolling_epa_lookup = {}
for row in features_2025.iter_rows(named=True):
    key = (row["team"], row["season"], row["week"])
    rolling_epa_lookup[key] = row["rolling_off_epa"]

print(f"Rolling EPA entries loaded: {len(rolling_epa_lookup)}")

# ══════════════════════════════════════════════════════════════
# LOAD AND PREPARE ODDS DATA
# ══════════════════════════════════════════════════════════════

print("Loading historical odds data...")
odds_df = pl.read_excel(str(Path(__file__).parent.parent / "data" / "external" / "nfl.xlsx"))

odds_2025 = odds_df.filter(
    (pl.col("Date") >= pl.date(2025, 9, 1)) &
    (pl.col("Date") <= pl.date(2026, 2, 15))
)

odds_2025 = odds_2025.with_columns([
    pl.col("Home Team").replace(TEAM_NAME_TO_ABBR).alias("home_abbr"),
    pl.col("Away Team").replace(TEAM_NAME_TO_ABBR).alias("away_abbr"),
    (1.0 / pl.col("Home Odds Close")).round(4).alias("book_home_ml_prob"),
    (1.0 / pl.col("Away Odds Close")).round(4).alias("book_away_ml_prob"),
])

odds_2025 = odds_2025.filter(
    pl.col("Home Odds Close").is_not_null() &
    pl.col("Home Line Close").is_not_null()
)

# ══════════════════════════════════════════════════════════════
# MATCH ODDS TO ROLLING FEATURES
# Need to figure out which week each game corresponds to.
# Since we don't have week numbers in the odds CSV, we'll
# assign week numbers by sorting games chronologically
# within the season and mapping dates to approximate weeks.
# ══════════════════════════════════════════════════════════════

# Get the mapping from (team, game_id) -> week from features
week_lookup = {}
for row in features_2025.iter_rows(named=True):
    # Store by (team, season, week) and also build a date-based fallback
    week_lookup[(row["team"], row["season"], row["week"])] = row["rolling_off_epa"]

# Build a date-to-week mapping from the features data
# Each unique game_id maps to a specific week
game_week_map = {}
for row in features_2025.iter_rows(named=True):
    game_week_map[row["game_id"]] = row["week"]

# For matching odds to features, we'll look up by team + approximate week
# Use the schedule_data to get game_ids with dates
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
schedule = connection.execute("""
    SELECT game_id, season, week, home_team, away_team, gameday
    FROM schedule_data
    WHERE season >= 2025
""").pl()
connection.close()

# Build lookup: (home_team_abbr, away_team_abbr, season) -> (week, game_id)
# Using home+away+season as key since a specific matchup happens once per season
game_lookup = {}
for row in schedule.iter_rows(named=True):
    key = (row["home_team"], row["away_team"], row["season"])
    game_lookup[key] = {"week": row["week"], "game_id": row["game_id"]}

print(f"Schedule entries for matching: {len(game_lookup)}")
print(f"Odds games to process: {odds_2025.shape[0]}")

# ══════════════════════════════════════════════════════════════
# RUN THE BACKTEST
# ══════════════════════════════════════════════════════════════

N_SIMS = 10000
print(f"\nRunning {N_SIMS} simulations per game...")

results = []
matched = 0
unmatched = 0

for i, row in enumerate(odds_2025.iter_rows(named=True)):
    home = row["home_abbr"]
    away = row["away_abbr"]
    book_spread = row["Home Line Close"]
    book_home_ml_prob = row["book_home_ml_prob"]
    actual_home_score = row["Home Score"]
    actual_away_score = row["Away Score"]
    actual_margin = actual_home_score - actual_away_score
    actual_home_covered = (actual_margin + book_spread) > 0
    actual_home_won = actual_home_score > actual_away_score

    # Try to find this game in schedule to get the week
    season = 2025
    game_info = game_lookup.get((home, away, season))

    if game_info is None:
        # Try 2026 season (late-season / playoff games)
        game_info = game_lookup.get((home, away, 2026))
        if game_info:
            season = 2026

    if game_info:
        week = game_info["week"]
        # Look up team-specific rolling EPA
        home_epa = rolling_epa_lookup.get((home, season, week), 0.0)
        away_epa = rolling_epa_lookup.get((away, season, week), 0.0)
        matched += 1
    else:
        # Fallback to league average if can't match
        home_epa = 0.0
        away_epa = 0.0
        week = 0
        unmatched += 1

    # Apply home-field advantage
    home_epa_adjusted = home_epa + HOME_EPA_BUMP

    # Simulate with team-specific EPA
    sim = simulate_game_probabilities(
        n_sims=N_SIMS,
        spread=book_spread,
        home_epa=home_epa_adjusted,
        away_epa=away_epa,
        seed=42 + i,
    )

    results.append({
        "date": row["Date"],
        "home": home,
        "away": away,
        "week": week,
        "home_epa": round(home_epa, 4),
        "away_epa": round(away_epa, 4),
        "book_spread": book_spread,
        "book_home_ml_prob": book_home_ml_prob,
        "sim_spread_prob": round(sim["p_home_covers"], 4),
        "sim_ml_prob": round(sim["p_home_wins"], 4),
        "actual_home_score": actual_home_score,
        "actual_away_score": actual_away_score,
        "actual_home_covered": actual_home_covered,
        "actual_home_won": actual_home_won,
    })

    if (i + 1) % 50 == 0:
        print(f"  Processed {i + 1} games...")

results_df = pl.DataFrame(results)
print(f"\nBacktest complete: {results_df.shape[0]} games")
print(f"Matched to schedule: {matched}, Unmatched: {unmatched}")

# ══════════════════════════════════════════════════════════════
# EVALUATION 1: CALIBRATION — SPREAD
# ══════════════════════════════════════════════════════════════

bins = [(0.0, 0.3), (0.3, 0.4), (0.4, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 1.0)]

print("\n" + "=" * 60)
print("CALIBRATION — SPREAD")
print("=" * 60)
print(f"{'Bin':>12}  {'Count':>6}  {'Predicted':>10}  {'Actual':>8}  {'Gap':>8}")
print("-" * 52)

for lo, hi in bins:
    bin_df = results_df.filter(
        (pl.col("sim_spread_prob") >= lo) & (pl.col("sim_spread_prob") < hi)
    )
    if bin_df.height == 0:
        continue
    predicted = bin_df["sim_spread_prob"].mean()
    actual = bin_df["actual_home_covered"].mean()
    gap = actual - predicted
    print(f"  [{lo:.2f}-{hi:.2f})  {bin_df.height:>6}  {predicted:>10.4f}  {actual:>8.4f}  {gap:>+8.4f}")

# ══════════════════════════════════════════════════════════════
# EVALUATION 2: CALIBRATION — MONEYLINE
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("CALIBRATION — MONEYLINE")
print("=" * 60)
print(f"{'Bin':>12}  {'Count':>6}  {'Predicted':>10}  {'Actual':>8}  {'Gap':>8}")
print("-" * 52)

for lo, hi in bins:
    bin_df = results_df.filter(
        (pl.col("sim_ml_prob") >= lo) & (pl.col("sim_ml_prob") < hi)
    )
    if bin_df.height == 0:
        continue
    predicted = bin_df["sim_ml_prob"].mean()
    actual = bin_df["actual_home_won"].mean()
    gap = actual - predicted
    print(f"  [{lo:.2f}-{hi:.2f})  {bin_df.height:>6}  {predicted:>10.4f}  {actual:>8.4f}  {gap:>+8.4f}")

# ══════════════════════════════════════════════════════════════
# EVALUATION 3: ACCURACY COMPARISON
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("ACCURACY COMPARISON")
print("=" * 60)

total = results_df.height

book_correct = results_df.filter(
    ((pl.col("book_home_ml_prob") > 0.5) & pl.col("actual_home_won")) |
    ((pl.col("book_home_ml_prob") <= 0.5) & ~pl.col("actual_home_won"))
).height

sim_correct = results_df.filter(
    ((pl.col("sim_ml_prob") > 0.5) & pl.col("actual_home_won")) |
    ((pl.col("sim_ml_prob") <= 0.5) & ~pl.col("actual_home_won"))
).height

print(f"Book ML accuracy:      {book_correct}/{total} ({book_correct/total*100:.1f}%)")
print(f"Simulator ML accuracy: {sim_correct}/{total} ({sim_correct/total*100:.1f}%)")

sim_favors_cover = results_df.filter(pl.col("sim_spread_prob") > 0.5)
sim_favors_not = results_df.filter(pl.col("sim_spread_prob") <= 0.5)
cover_correct = sim_favors_cover.filter(pl.col("actual_home_covered")).height
not_correct = sim_favors_not.filter(~pl.col("actual_home_covered")).height
spread_accuracy = (cover_correct + not_correct) / total

print(f"Spread accuracy:       {cover_correct + not_correct}/{total} ({spread_accuracy*100:.1f}%)")

# ══════════════════════════════════════════════════════════════
# EVALUATION 4: SAMPLE PREDICTIONS (week 5+, differentiated)
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SAMPLE PREDICTIONS (Week 5+)")
print("=" * 60)

sample = results_df.filter(pl.col("week") >= 5).select([
    "home", "away", "week", "home_epa", "away_epa",
    "book_spread", "sim_ml_prob", "book_home_ml_prob",
    "actual_home_score", "actual_away_score"
]).head(15)
print(sample)

# ══════════════════════════════════════════════════════════════
# SUMMARY — v1 vs v2 comparison
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

spread_cal_errors = []
for lo, hi in bins:
    bin_df = results_df.filter(
        (pl.col("sim_spread_prob") >= lo) & (pl.col("sim_spread_prob") < hi)
    )
    if bin_df.height >= 5:
        predicted = bin_df["sim_spread_prob"].mean()
        actual = bin_df["actual_home_covered"].mean()
        spread_cal_errors.append(abs(actual - predicted))

ml_cal_errors = []
for lo, hi in bins:
    bin_df = results_df.filter(
        (pl.col("sim_ml_prob") >= lo) & (pl.col("sim_ml_prob") < hi)
    )
    if bin_df.height >= 5:
        predicted = bin_df["sim_ml_prob"].mean()
        actual = bin_df["actual_home_won"].mean()
        ml_cal_errors.append(abs(actual - predicted))

print(f"Spread mean calibration error: {np.mean(spread_cal_errors):.4f}" if spread_cal_errors else "Spread: insufficient data")
print(f"ML mean calibration error:     {np.mean(ml_cal_errors):.4f}" if ml_cal_errors else "ML: insufficient data")
print(f"Book ML accuracy:              {book_correct/total*100:.1f}%")
print(f"Simulator ML accuracy:         {sim_correct/total*100:.1f}%")
print(f"Simulator spread accuracy:     {spread_accuracy*100:.1f}%")
print("\n── Compare vs v1 (league average for all) ──")
print("v1 spread calibration error: 0.1151")
print("v1 ML calibration error:     0.0436")
print("v1 book ML accuracy:         66.2%")
print("v1 simulator ML accuracy:    46.9%")
print("v1 spread accuracy:          50.2%")
print("\nImprovements from team-specific EPA + home advantage:")
print(f"  Spread cal error: 0.1151 -> {np.mean(spread_cal_errors):.4f}" if spread_cal_errors else "")
print(f"  ML cal error:     0.0436 -> {np.mean(ml_cal_errors):.4f}" if ml_cal_errors else "")
print(f"  ML accuracy:      46.9% -> {sim_correct/total*100:.1f}%")
print(f"  Spread accuracy:  50.2% -> {spread_accuracy*100:.1f}%")