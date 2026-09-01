from pathlib import Path

import duckdb
import polars as pl
import numpy as np
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

# ══════════════════════════════════════════════════════════════
# PURPOSE OF THIS SCRIPT
# The offense EPA model gives a single POINT prediction per game.
# A simulator can't use a point prediction directly — it needs a
# DISTRIBUTION to draw from, so that each simulated game reflects
# the real game-to-game noise we measured.
#
# This script:
#   1. Rebuilds the model (same as the training script)
#   2. Measures the model's residuals (actual - predicted)
#   3. Checks whether those residuals justify a normal approximation
#   4. Decides whether one fixed spread is enough, or if spread
#      should vary by situation (the Option A vs Option B question)
#   5. Defines the draw function the simulator will actually call
# ══════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────
# STEP 0: REBUILD THE MODEL
# Same load / split / fit as the training script. Nothing new here —
# we need a trained model in memory before we can study its errors.
# ──────────────────────────────────────────────
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "team_game_features.sql"
result = connection.execute(sql_path.read_text()).pl()
connection.close()

feature_cols = [
    "rolling_off_epa",
    "rolling_off_pass_epa",
    "rolling_off_rush_epa",
    "rolling_pass_rate",
    "rolling_opp_def_epa",
    "rolling_opp_def_pass_epa",
    "rolling_opp_def_rush_epa",
    "is_home",
]
target_col = "off_epa"

TRAIN_SEASONS = [2019, 2020, 2021, 2022, 2023]
TEST_SEASONS = [2024, 2025]

train_df = result.filter(pl.col("season").is_in(TRAIN_SEASONS))
test_df = result.filter(pl.col("season").is_in(TEST_SEASONS))

X_train = train_df.select(feature_cols).to_numpy()
y_train = train_df[target_col].to_numpy()
X_test = test_df.select(feature_cols).to_numpy()
y_test = test_df[target_col].to_numpy()

model = lgb.LGBMRegressor(
    n_estimators=200,
    learning_rate=0.05,
    max_depth=4,
    random_state=42,
)
model.fit(X_train, y_train)
predictions = model.predict(X_test)

# ──────────────────────────────────────────────
# STEP 1: COMPUTE RESIDUALS
# A residual is the gap between what actually happened and what
# the model predicted, for each test-set game:
#     residual = actual - predicted
# Positive residual = model UNDER-predicted (real value was higher)
# Negative residual = model OVER-predicted
#
# The SPREAD of these residuals is the real game-to-game noise the
# simulator needs to reproduce. We measure it here rather than
# guessing it.
# ──────────────────────────────────────────────
residuals = y_test - predictions

# ──────────────────────────────────────────────
# STEP 2: CHECK THE RESIDUALS SUPPORT A NORMAL APPROXIMATION
# We plan to model uncertainty as a normal distribution centered
# on each prediction. That's only reasonable if the residuals are:
#   (a) roughly centered on zero — the model isn't systematically
#       biased high or low, and
#   (b) roughly symmetric — errors in both directions are similar,
#       so a symmetric (normal) distribution is a fair description.
#
# We also compare residual std to RMSE. They measure similar things;
# RMSE weights large errors a bit more heavily, so it's usually
# slightly larger. If they're close, the error sizes are consistent.
# ──────────────────────────────────────────────
residual_mean = residuals.mean()
residual_std = residuals.std()
rmse = root_mean_squared_error(y_test, predictions)

# A crude symmetry check: how many residuals fall on each side of 0.
# Close to a 50/50 split supports the symmetric-normal assumption.
n_positive = int((residuals > 0).sum())
n_negative = int((residuals < 0).sum())

print("── Residual diagnostics ──")
print(f"Residual mean:      {residual_mean:.4f}   (want: close to 0 = unbiased)")
print(f"Residual std:       {residual_std:.4f}")
print(f"RMSE (for compare): {rmse:.4f}   (want: close to residual std)")
print(f"Above zero: {n_positive}   Below zero: {n_negative}   "
      f"(want: roughly even = symmetric)")

# Percentiles give a fuller picture than std alone — if the middle
# looks tight but the extremes are far out, the distribution has
# heavy tails and a plain normal might understate rare blowups.
p05, p25, p50, p75, p95 = np.percentile(residuals, [5, 25, 50, 75, 95])
print(f"Residual percentiles  5%={p05:.3f}  25%={p25:.3f}  "
      f"50%={p50:.3f}  75%={p75:.3f}  95%={p95:.3f}")

# ──────────────────────────────────────────────
# STEP 3: DOES THE SPREAD VARY BY WEEK? (Option A vs Option B)
# Option A: use ONE fixed spread for every simulated draw.
# Option B: let the spread vary by situation (e.g. early-season
#           predictions being less reliable than late-season ones).
#
# We test this directly: bucket the test residuals by early vs late
# season and compare their spreads. If early-season residuals are
# clearly wider, Option B is worth the extra complexity. If they're
# about the same, Option A (one fixed spread) is a fair simplification.
# ──────────────────────────────────────────────
diag = test_df.select(["week"]).with_columns(
    pl.Series("residual", residuals)
)

early = diag.filter(pl.col("week") <= 4)["residual"].to_numpy()
late = diag.filter(pl.col("week") >= 10)["residual"].to_numpy()

print("\n── Spread by season stage ──")
print(f"Early-season (wk <= 4) residual std: {early.std():.4f}  (n={len(early)})")
print(f"Late-season  (wk >= 10) residual std: {late.std():.4f}  (n={len(late)})")
print("If these are close -> Option A (one fixed spread) is fine.")
print("If early is clearly larger -> Option B (spread varies) is worth it.")

# ──────────────────────────────────────────────
# STEP 4: THE DRAW FUNCTION THE SIMULATOR WILL CALL
# This is the actual output of all the analysis above: a function
# that turns a point prediction into a plausible drawn value.
#
# Instead of using the model's point prediction directly, the
# simulator calls this once per simulation per team. Each call
# returns a different plausible EPA/play, centered on the model's
# prediction and spread according to the measured residual std.
#
# Over thousands of simulations, the collection of draws forms a
# distribution — exactly what a Monte Carlo simulator needs, and
# conceptually the same idea as sampling from a PyMC posterior,
# just approximated because LightGBM gives a point estimate rather
# than a full posterior.
# ──────────────────────────────────────────────
def draw_offense_epa(point_prediction, spread=residual_std, rng=None):
    """Draw one plausible offensive EPA/play for a simulated game.

    point_prediction : the LightGBM model's predicted off_epa
    spread           : std of the distribution to draw from
                       (defaults to the measured residual std)
    rng              : optional numpy Generator for reproducibility
    """
    if rng is None:
        rng = np.random.default_rng()
    return rng.normal(loc=point_prediction, scale=spread)


# ──────────────────────────────────────────────
# STEP 5: QUICK DEMONSTRATION
# Take the first test-set prediction and draw from its distribution
# a few thousand times. The draws should center near the prediction
# and spread out by roughly residual_std — confirming the wrapper
# behaves the way the simulator will rely on.
# ──────────────────────────────────────────────
rng = np.random.default_rng(42)
example_prediction = predictions[0]
draws = draw_offense_epa(example_prediction, rng=rng)  # single draw
many_draws = np.array([draw_offense_epa(example_prediction, rng=rng) for _ in range(5000)])

print("\n── Draw function demo ──")
print(f"Point prediction:      {example_prediction:.4f}")
print(f"Single random draw:    {draws:.4f}")
print(f"5000 draws -> mean:    {many_draws.mean():.4f}  (should ~= prediction)")
print(f"5000 draws -> std:     {many_draws.std():.4f}  (should ~= residual std)")