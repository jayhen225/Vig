from pathlib import Path

import duckdb
import polars as pl
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

# ──────────────────────────────────────────────
# STEP 1: LOAD DATA
# Same pattern as every other script in this project —
# connect to the warehouse, run the SQL file, get a DataFrame.
# ──────────────────────────────────────────────
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "team_game_features.sql"
result = connection.execute(sql_path.read_text()).pl()
connection.close()

print(f"Total rows: {result.shape[0]}")
print(f"Seasons available: {sorted(result['season'].unique().to_list())}")

# ──────────────────────────────────────────────
# STEP 2: DEFINE FEATURES AND TARGET
# Features = everything known BEFORE the game (rolling stats, home/away)
# Target = the actual same-game off_epa we're trying to predict
#
# This split matters: every feature column here is a "rolling_"
# column, meaning it was computed only from PRIOR games. The target
# (off_epa) is the real outcome of the game we're predicting.
# That's what makes this leakage-free.
# ──────────────────────────────────────────────
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

# ──────────────────────────────────────────────
# STEP 3: SPLIT BY SEASON, NOT RANDOMLY
# This is the walk-forward discipline flagged at the very start
# of this project. A random split could let a 2024 game end up
# in training while a 2019 game ends up in the test set — meaning
# the model could implicitly "see the future" relative to what
# it's being tested against.
#
# Splitting by season guarantees every test-set game happens
# chronologically AFTER every training-set game, which mirrors
# how the model would actually be used in production: trained on
# the past, evaluated on what comes next.
# ──────────────────────────────────────────────
TRAIN_SEASONS = [2019, 2020, 2021, 2022, 2023]
TEST_SEASONS = [2024, 2025]

train_df = result.filter(pl.col("season").is_in(TRAIN_SEASONS))
test_df = result.filter(pl.col("season").is_in(TEST_SEASONS))
test_df_diagnostic = test_df.filter(pl.col("week") >= 5)  # for later diagnostic checks

print(f"Train rows: {train_df.shape[0]} (seasons {TRAIN_SEASONS})")
print(f"Test rows: {test_df.shape[0]} (seasons {TEST_SEASONS})")


# Convert to numpy arrays — LightGBM's sklearn-style API expects
# array-like X (2D: rows x features) and y (1D: target values)
X_train = train_df.select(feature_cols).to_numpy()
y_train = train_df[target_col].to_numpy()

X_test = test_df.select(feature_cols).to_numpy()
y_test = test_df[target_col].to_numpy()

X_test_diag = test_df_diagnostic.select(feature_cols).to_numpy()
y_test_diag = test_df_diagnostic[target_col].to_numpy()


# ──────────────────────────────────────────────
# STEP 4: FIT THE MODEL
# LGBMRegressor because off_epa is a continuous number, not a
# category — this is a regression problem, not classification.
#
# n_estimators / learning_rate / max_depth are starting points,
# not tuned values. Worth revisiting these once you see how the
# model performs — but don't tune against the test set itself,
# since that would leak test-set information back into your
# modeling choices. Use a validation split within the training
# seasons if you want to tune properly later.
# ──────────────────────────────────────────────
model = lgb.LGBMRegressor(
    n_estimators=200,
    learning_rate=0.05,
    max_depth=4,       # shallow trees — this dataset isn't huge,
                        # deep trees would likely overfit
    random_state=42,
)

model.fit(X_train, y_train)

# ──────────────────────────────────────────────
# STEP 5: EVALUATE ON HELD-OUT SEASONS
# MAE (mean absolute error): average size of the prediction error,
# in the same units as EPA itself — easy to interpret directly.
#
# RMSE (root mean squared error): similar, but penalizes large
# errors more heavily. Comparing MAE vs RMSE tells you whether
# errors are consistent or occasionally very large (a big gap
# between the two suggests some predictions are way off).
# ──────────────────────────────────────────────
predictions = model.predict(X_test)
predictions_diag = model.predict(X_test_diag)

mae = mean_absolute_error(y_test, predictions)
rmse = root_mean_squared_error(y_test, predictions)

mae_diag = mean_absolute_error(y_test_diag, predictions_diag)
rmse_diag = root_mean_squared_error(y_test_diag, predictions_diag)

print(f"\nMAE:  {mae:.4f}")
print(f"RMSE: {rmse:.4f}")

# NAIVE BASELINE COMPARISON
# What if we just predicted the league average for
# every single row, no model at all? If our model's
# MAE isn't meaningfully better than this, the model
# isn't learning much beyond "predict the average."
# ──────────────────────────────────────────────
naive_prediction = y_train.mean()
naive_mae = mean_absolute_error(y_test, [naive_prediction] * len(y_test))
print(f"Naive baseline MAE: {naive_mae:.4f}")

print(f"\n[Week 5+ only] MAE:  {mae_diag:.4f}")
print(f"[Week 5+ only] RMSE: {rmse_diag:.4f}")

# ──────────────────────────────────────────────
# STEP 6: SANITY CHECK — LOOK AT REAL EXAMPLES
# Never trust a single error number blindly. Look at a handful of
# actual predictions side by side with real outcomes, and check
# they move in sensible directions given the input features.
# ──────────────────────────────────────────────
comparison = test_df.select(["team", "season", "week", target_col]).with_columns(
    pl.Series("predicted_off_epa", predictions).round(4)
)
print("\nSample predictions vs actual:")
print(comparison.head(15))

comparison_diag = test_df_diagnostic.select(["team", "season", "week", target_col]).with_columns(
    pl.Series("predicted_off_epa", predictions_diag).round(4)
)
print("\n[Week 5+ only] Sample predictions vs actual:")
print(comparison_diag.head(15))

# ──────────────────────────────────────────────
# STEP 7: FEATURE IMPORTANCE
# Which features is the model actually relying on? This is a
# cheap, useful check — if rolling_off_epa dominates everything
# else, that's expected (a team's own recent efficiency should be
# the strongest predictor of their next game's efficiency). If
# something surprising dominates, worth investigating why.
# ──────────────────────────────────────────────
importance = pl.DataFrame({
    "feature": feature_cols,
    "importance": model.feature_importances_,
}).sort("importance", descending=True)
print("\nFeature importance:")
print(importance)