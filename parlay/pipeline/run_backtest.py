"""Backtest: Spreads & Moneylines vs Historical Closing Odds (2025 season)

For each 2025 game:
  1. Simulate 10,000 game outcomes using team-level EPA + noise
  2. Compute P(home covers closing spread) and P(home wins)
  3. Compare against the book's closing implied probability
  4. Record whether the actual result matched

Evaluation:
  - Calibration: do legs priced at X% actually hit X% of the time?
  - CLV: does our price move in the same direction as the closing line?
  - Spread/ML accuracy: how often is our predicted side correct?

Note: this uses the free CSV (spreads/moneylines only, no player props).
Player-level traces are NOT needed for this — only team-level simulation.
"""

from pathlib import Path

import numpy as np
import polars as pl

# ══════════════════════════════════════════════════════════════
# CONSTANTS (from earlier analysis)
# ══════════════════════════════════════════════════════════════
LEAGUE_AVG_POINTS = 22.92
LEAGUE_AVG_PLAYS = 62.3
PLAYS_SPREAD = 8.5
LEAGUE_AVG_DEF_EPA = 0.0024
DEF_EPA_SPREAD = 0.2170
OFF_EPA_SPREAD = 0.2091
DEFAULT_PASS_RATE = 0.58

# ══════════════════════════════════════════════════════════════
# TEAM NAME MAPPING (CSV full names -> schedule_data abbreviations)
# ══════════════════════════════════════════════════════════════
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Los Angeles Rams": "LA",
    "Los Angeles Chargers": "LAC",
    "Las Vegas Raiders": "LV",
    "Oakland Raiders": "OAK",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

# ══════════════════════════════════════════════════════════════
# SIMULATION FUNCTIONS (team-level only, no player traces needed)
# ══════════════════════════════════════════════════════════════

def simulate_game_scores(rng, home_epa=0.0, away_epa=0.0):
    """Simulate one game, return (home_score, away_score)."""
    # Home team
    home_off = rng.normal(loc=home_epa, scale=OFF_EPA_SPREAD)
    away_def = rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=DEF_EPA_SPREAD)
    home_matchup = home_off + away_def
    home_plays = max(30, round(rng.normal(loc=LEAGUE_AVG_PLAYS, scale=PLAYS_SPREAD)))
    home_points = max(0, round(LEAGUE_AVG_POINTS + (home_matchup * home_plays)))

    # Away team
    away_off = rng.normal(loc=away_epa, scale=OFF_EPA_SPREAD)
    home_def = rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=DEF_EPA_SPREAD)
    away_matchup = away_off + home_def
    away_plays = max(30, round(rng.normal(loc=LEAGUE_AVG_PLAYS, scale=PLAYS_SPREAD)))
    away_points = max(0, round(LEAGUE_AVG_POINTS + (away_matchup * away_plays)))

    return home_points, away_points


def simulate_game_probabilities(n_sims, spread, home_epa=0.0, away_epa=0.0, seed=42):
    """Run N simulations and return P(home covers spread) and P(home wins).

    spread : the book's closing spread from the home team's perspective
             (negative = home favorite, positive = home underdog)
    """
    rng = np.random.default_rng(seed)
    spread_covers = 0
    home_wins = 0

    for _ in range(n_sims):
        home_score, away_score = simulate_game_scores(rng, home_epa, away_epa)
        margin = home_score - away_score

        # Spread: margin + spread > 0 means home covered
        if margin + spread > 0:
            spread_covers += 1

        # Moneyline: home wins outright
        if home_score > away_score:
            home_wins += 1

    return {
        "p_home_covers": spread_covers / n_sims,
        "p_home_wins": home_wins / n_sims,
    }


# ══════════════════════════════════════════════════════════════
# LOAD AND PREPARE THE ODDS DATA
# ══════════════════════════════════════════════════════════════

print("Loading historical odds data...")
odds_df = pl.read_excel(str(Path(__file__).parent.parent / "data" / "external" / "nfl.xlsx"))

# Filter to 2025 regular season (Sept 2025 through Jan 2026)
odds_2025 = odds_df.filter(
    (pl.col("Date") >= pl.date(2025, 9, 1)) &
    (pl.col("Date") <= pl.date(2026, 2, 15))
)

# Convert team names to abbreviations
odds_2025 = odds_2025.with_columns([
    pl.col("Home Team").replace(TEAM_NAME_TO_ABBR).alias("home_abbr"),
    pl.col("Away Team").replace(TEAM_NAME_TO_ABBR).alias("away_abbr"),
])

# Convert decimal odds to implied probability
# Decimal odds of 1.91 -> implied prob = 1/1.91 = 0.524
odds_2025 = odds_2025.with_columns([
    (1.0 / pl.col("Home Odds Close")).round(4).alias("book_home_ml_prob"),
    (1.0 / pl.col("Away Odds Close")).round(4).alias("book_away_ml_prob"),
])

# Drop rows with missing odds or spreads
odds_2025 = odds_2025.filter(
    pl.col("Home Odds Close").is_not_null() &
    pl.col("Home Line Close").is_not_null()
)

print(f"2025 games with odds: {odds_2025.shape[0]}")

# ══════════════════════════════════════════════════════════════
# RUN THE BACKTEST
# ══════════════════════════════════════════════════════════════

N_SIMS = 10000

print(f"Running {N_SIMS} simulations per game...")

results = []

for i, row in enumerate(odds_2025.iter_rows(named=True)):
    # Book's closing data
    book_spread = row["Home Line Close"]
    book_home_ml_prob = row["book_home_ml_prob"]
    actual_home_score = row["Home Score"]
    actual_away_score = row["Away Score"]
    actual_margin = actual_home_score - actual_away_score

    # Did the actual result cover / win?
    actual_home_covered = (actual_margin + book_spread) > 0
    actual_home_won = actual_home_score > actual_away_score

    # Simulate
    sim = simulate_game_probabilities(
        n_sims=N_SIMS,
        spread=book_spread,
        home_epa=0.0,   # using league average (EPA model barely beat naive)
        away_epa=0.0,
        seed=42 + i,     # different seed per game for independence
    )

    results.append({
        "date": row["Date"],
        "home": row["home_abbr"],
        "away": row["away_abbr"],
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
print(f"\nBacktest complete: {results_df.shape[0]} games processed")

# ══════════════════════════════════════════════════════════════
# EVALUATION 1: CALIBRATION
# Bin predictions by probability, check if actual hit rates match.
# A well-calibrated model: legs priced at 60% should hit ~60%.
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("CALIBRATION — SPREAD")
print("=" * 60)

# Create probability bins
bins = [(0.0, 0.3), (0.3, 0.4), (0.4, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 1.0)]

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
# EVALUATION 2: CLV (Closing Line Value)
# Compare simulator's price direction against the book's price.
# If we price home ML at 55% and the book has it at 50%,
# we're saying the home team is underpriced. If the closing
# line moved toward 53%, that's CLV — the market agreed with us.
#
# With this dataset we only have closing lines (no opening lines
# to compare movement against), so we measure something simpler:
# when our price disagrees with the book's price, who's closer
# to the actual outcome rate?
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("PRICE COMPARISON — MONEYLINE")
print("=" * 60)

# De-vig the book's ML odds (they sum to > 1 due to vig)
results_df = results_df.with_columns([
    (pl.col("book_home_ml_prob") / 
     (pl.col("book_home_ml_prob") + (1.0 - pl.col("book_home_ml_prob").clip(0.01, 0.99)))
    ).alias("book_devigged_home_prob")
])

# Compare overall accuracy
book_correct = results_df.filter(
    ((pl.col("book_home_ml_prob") > 0.5) & pl.col("actual_home_won")) |
    ((pl.col("book_home_ml_prob") <= 0.5) & ~pl.col("actual_home_won"))
).height

sim_correct = results_df.filter(
    ((pl.col("sim_ml_prob") > 0.5) & pl.col("actual_home_won")) |
    ((pl.col("sim_ml_prob") <= 0.5) & ~pl.col("actual_home_won"))
).height

total = results_df.height
print(f"Book picked correct ML winner: {book_correct}/{total} ({book_correct/total*100:.1f}%)")
print(f"Simulator picked correct ML winner: {sim_correct}/{total} ({sim_correct/total*100:.1f}%)")

# ══════════════════════════════════════════════════════════════
# EVALUATION 3: SPREAD ACCURACY
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SPREAD ACCURACY")
print("=" * 60)

# When simulator says > 50% chance of covering, how often did it cover?
sim_favors_cover = results_df.filter(pl.col("sim_spread_prob") > 0.5)
sim_favors_not = results_df.filter(pl.col("sim_spread_prob") <= 0.5)

cover_correct = sim_favors_cover.filter(pl.col("actual_home_covered")).height
not_correct = sim_favors_not.filter(~pl.col("actual_home_covered")).height

print(f"Sim says home covers (>50%): {sim_favors_cover.height} games, correct {cover_correct} ({cover_correct/max(1,sim_favors_cover.height)*100:.1f}%)")
print(f"Sim says home doesn't cover (<=50%): {sim_favors_not.height} games, correct {not_correct} ({not_correct/max(1,sim_favors_not.height)*100:.1f}%)")
print(f"Overall spread accuracy: {(cover_correct + not_correct)}/{total} ({(cover_correct + not_correct)/total*100:.1f}%)")

# ══════════════════════════════════════════════════════════════
# EVALUATION 4: SAMPLE PREDICTIONS
# Spot-check a few games to see if the numbers make sense
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SAMPLE PREDICTIONS")
print("=" * 60)

sample = results_df.select([
    "date", "home", "away", "book_spread",
    "book_home_ml_prob", "sim_ml_prob",
    "sim_spread_prob", "actual_home_score", "actual_away_score"
]).head(15)
print(sample)

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Compute mean absolute calibration error for spreads
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

print(f"Spread mean calibration error: {np.mean(spread_cal_errors):.4f}" if spread_cal_errors else "Spread calibration: insufficient data")
print(f"ML mean calibration error:     {np.mean(ml_cal_errors):.4f}" if ml_cal_errors else "ML calibration: insufficient data")
print(f"Book ML accuracy:              {book_correct/total*100:.1f}%")
print(f"Simulator ML accuracy:         {sim_correct/total*100:.1f}%")
print(f"Simulator spread accuracy:     {(cover_correct + not_correct)/total*100:.1f}%")
print(f"\nNote: this backtest uses league-average EPA for all teams")
print(f"(offensive EPA model barely beat naive). Real signal lives")
print(f"in the player-level usage models, tested via prop calibration")
print(f"once prop odds data is available.")
