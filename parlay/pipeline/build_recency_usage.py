"""Layer 1: Recency-Weighted Usage Estimates

Problem: the PyMC posteriors weight all career games equally. A player
who was a backup for 2 years (8% target share) then became a starter
this season (24%) gets a posterior centered around 14%. The book sets
this week's line based on 24%. That gap is a major error source.

Solution: compute a recent rolling average (last 6 games) and blend
it with the career posterior. The posterior still provides the
UNCERTAINTY (distribution width), but the CENTER shifts toward
recent performance.

Output: a lookup table of recency-adjusted usage estimates per player,
saved as a Parquet file the simulator can load.
"""

from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import polars as pl
from scipy.special import expit

DATA_DIR = Path(__file__).parent.parent / "data"
SQL_DIR = Path(__file__).parent / "sql"
DB_PATH = DATA_DIR / "nfl_data.duckdb"

# ══════════════════════════════════════════════════════════════
# STEP 1: LOAD ROLLING USAGE DATA
# ══════════════════════════════════════════════════════════════

print("Step 1: Loading rolling usage data...")
connection = duckdb.connect(str(DB_PATH), read_only=True)
sql_path = SQL_DIR / "rolling_usage.sql"
rolling_df = connection.execute(sql_path.read_text()).pl()
connection.close()

print(f"  Total rows: {rolling_df.shape[0]}")
print(f"  Metrics: {rolling_df['metric'].unique().to_list()}")

# ══════════════════════════════════════════════════════════════
# STEP 2: LOAD CAREER POSTERIORS
# ══════════════════════════════════════════════════════════════

print("\nStep 2: Loading career posteriors...")

# Target share trace
ts_trace_path = DATA_DIR / "traces" / "target_share_trace_backtest.nc"
if not ts_trace_path.exists():
    ts_trace_path = DATA_DIR / "traces" / "target_share_trace.nc"

ts_trace = az.from_netcdf(str(ts_trace_path))

connection = duckdb.connect(str(DB_PATH), read_only=True)
ts_result = connection.execute(Path(SQL_DIR / "target_share.sql").read_text()).pl()
ts_result = ts_result.filter(pl.col("season") <= 2024)
ts_result = ts_result.with_columns(
    (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
)
ts_unique = ts_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
ts_names = ts_result.select(["gsis_id", "display_name"]).unique()
ts_indexed = ts_unique.join(ts_names, on="gsis_id")

# Extract posterior means and stds per player (on probability scale)
ts_draws = expit(ts_trace.posterior["player_mu"].values.reshape(
    -1, ts_trace.posterior["player_mu"].shape[-1]))

ts_posterior_stats = {}
for row in ts_indexed.iter_rows(named=True):
    idx = row["idx"]
    player_draws = ts_draws[:, idx]
    ts_posterior_stats[row["display_name"]] = {
        "posterior_mean": float(np.mean(player_draws)),
        "posterior_std": float(np.std(player_draws)),
        "gsis_id": row["gsis_id"],
    }

# Carry share trace
cs_trace = az.from_netcdf(str(DATA_DIR / "traces" / "carry_share_trace.nc"))
cs_result = connection.execute(Path(SQL_DIR / "carry_share.sql").read_text()).pl()
cs_result = cs_result.filter(pl.col("season") <= 2024)
cs_result = cs_result.with_columns(
    (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
)
cs_unique = cs_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
cs_names = cs_result.select(["gsis_id", "display_name"]).unique()
cs_indexed = cs_unique.join(cs_names, on="gsis_id")

cs_draws = expit(cs_trace.posterior["player_mu"].values.reshape(
    -1, cs_trace.posterior["player_mu"].shape[-1]))

cs_posterior_stats = {}
for row in cs_indexed.iter_rows(named=True):
    idx = row["idx"]
    player_draws = cs_draws[:, idx]
    cs_posterior_stats[row["display_name"]] = {
        "posterior_mean": float(np.mean(player_draws)),
        "posterior_std": float(np.std(player_draws)),
        "gsis_id": row["gsis_id"],
    }

connection.close()

print(f"  Target share posteriors: {len(ts_posterior_stats)} players")
print(f"  Carry share posteriors: {len(cs_posterior_stats)} players")

# ══════════════════════════════════════════════════════════════
# STEP 3: COMPUTE RECENCY-ADJUSTED ESTIMATES
#
# For each player's most recent game, compute:
#   adjusted_center = blend(recent_avg, career_posterior_mean)
#   adjusted_std = career_posterior_std (unchanged — uncertainty
#                  from the posterior is still valid)
#
# The blend formula:
#   weight = recent_games / (recent_games + k)
#   adjusted = weight * recent_avg + (1 - weight) * posterior_mean
#
# k controls how quickly recent data overrides the career average.
# k=3 means: with 3 recent games, recent form gets 50% weight.
# k=6 means: need 6 recent games for 50% weight.
# Lower k = trust recent form faster. Higher k = more conservative.
# ══════════════════════════════════════════════════════════════

RECENCY_K = 4  # 4 recent games = 50% weight on recent form

print(f"\nStep 3: Computing recency-adjusted estimates (k={RECENCY_K})...")

# Get the most recent row per player per metric
latest = (
    rolling_df
    .sort(["gsis_id", "metric", "season", "week"])
    .group_by(["gsis_id", "display_name", "metric"])
    .last()
)

adjusted_rows = []

for row in latest.iter_rows(named=True):
    player = row["display_name"]
    metric = row["metric"]
    recent_avg = row["recent_avg"]
    career_avg = row["career_avg"]
    recent_games = row["recent_games"]

    # Get the right posterior stats
    if metric == "target_share":
        posterior = ts_posterior_stats.get(player)
    elif metric == "carry_share":
        posterior = cs_posterior_stats.get(player)
    else:
        continue

    if posterior is None:
        continue

    posterior_mean = posterior["posterior_mean"]
    posterior_std = posterior["posterior_std"]

    # If no recent data, fall back to career posterior entirely
    if recent_avg is None or recent_games is None or recent_games == 0:
        adjusted_center = posterior_mean
        recency_weight = 0.0
    else:
        # Blend: recent form weighted by sample size
        recency_weight = recent_games / (recent_games + RECENCY_K)
        adjusted_center = recency_weight * recent_avg + (1 - recency_weight) * posterior_mean

    # How much did recency shift the estimate?
    shift = adjusted_center - posterior_mean

    adjusted_rows.append({
        "display_name": player,
        "gsis_id": row["gsis_id"],
        "metric": metric,
        "posterior_mean": round(posterior_mean, 4),
        "recent_avg": round(recent_avg, 4) if recent_avg is not None else None,
        "recent_games": recent_games,
        "recency_weight": round(recency_weight, 4),
        "adjusted_center": round(adjusted_center, 4),
        "posterior_std": round(posterior_std, 4),
        "shift": round(shift, 4),
    })

adjusted_df = pl.DataFrame(adjusted_rows)
print(f"  Adjusted estimates: {adjusted_df.shape[0]} player-metric pairs")

# ══════════════════════════════════════════════════════════════
# STEP 4: VERIFY — SHOW EXAMPLES
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("VERIFICATION: Players with large recency shifts")
print("=" * 60)

# Players whose recent form differs most from career average
big_shifts = (
    adjusted_df
    .filter(pl.col("recent_games") >= 4)
    .sort(pl.col("shift").abs(), descending=True)
    .head(15)
)

print(f"\n{'Player':<22} {'Metric':<15} {'Career':>8} {'Recent':>8} {'Adjusted':>8} {'Shift':>8} {'Games':>5}")
print("-" * 88)

for row in big_shifts.iter_rows(named=True):
    print(f"{row['display_name']:<22} {row['metric']:<15} "
          f"{row['posterior_mean']:>8.4f} {row['recent_avg']:>8.4f} "
          f"{row['adjusted_center']:>8.4f} {row['shift']:>+8.4f} {row['recent_games']:>5}")

# Players whose recent form matches career (stable roles)
print("\n" + "=" * 60)
print("VERIFICATION: Stable players (small shifts)")
print("=" * 60)

small_shifts = (
    adjusted_df
    .filter((pl.col("recent_games") >= 4) & (pl.col("shift").abs() < 0.005))
    .sort("posterior_mean", descending=True)
    .head(10)
)

print(f"\n{'Player':<22} {'Metric':<15} {'Career':>8} {'Recent':>8} {'Adjusted':>8} {'Shift':>8}")
print("-" * 82)

for row in small_shifts.iter_rows(named=True):
    print(f"{row['display_name']:<22} {row['metric']:<15} "
          f"{row['posterior_mean']:>8.4f} {row['recent_avg']:>8.4f} "
          f"{row['adjusted_center']:>8.4f} {row['shift']:>+8.4f}")

# ══════════════════════════════════════════════════════════════
# STEP 5: SUMMARY STATISTICS
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

for metric in ["target_share", "carry_share"]:
    metric_df = adjusted_df.filter(
        (pl.col("metric") == metric) & (pl.col("recent_games") >= 4)
    )
    if metric_df.height == 0:
        continue

    avg_shift = metric_df["shift"].abs().mean()
    max_shift = metric_df["shift"].abs().max()
    pct_shifted = (metric_df["shift"].abs() > 0.02).sum() / metric_df.height * 100

    print(f"\n  {metric} (players with 4+ recent games):")
    print(f"    Players: {metric_df.height}")
    print(f"    Average absolute shift: {avg_shift:.4f}")
    print(f"    Max absolute shift:     {max_shift:.4f}")
    print(f"    Players shifted > 2%:   {pct_shifted:.1f}%")

# ══════════════════════════════════════════════════════════════
# STEP 6: SAVE FOR SIMULATOR USE
# ══════════════════════════════════════════════════════════════

output_path = DATA_DIR / "recency_adjusted_usage.parquet"
adjusted_df.write_parquet(output_path)
print(f"\nSaved to {output_path}")
print("The simulator can load this to use adjusted centers instead of career posteriors.")