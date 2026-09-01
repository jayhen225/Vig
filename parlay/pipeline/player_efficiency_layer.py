"""Player efficiency layer for the simulator.

Computes shrunk efficiency estimates (yards per target, yards per carry,
yards per attempt) for each player, blending their individual average
with their position-group average weighted by sample size. Provides
draw functions that the simulator calls to generate plausible per-game
efficiency values with calibrated uncertainty.

This is the "lighter-weight partial pooling" approach — same concept
as the PyMC hierarchical models but computed directly, since efficiency
metrics are stable enough per player that full MCMC isn't needed.
"""

from pathlib import Path

import duckdb
import polars as pl
import numpy as np

# ──────────────────────────────────────────────
# STEP 1: LOAD EFFICIENCY DATA
# One row per player per game, with yards_per_opportunity
# for each metric (yards_per_target, yards_per_carry,
# yards_per_attempt).
# ──────────────────────────────────────────────
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "player_efficiency.sql"
result = connection.execute(sql_path.read_text()).pl()
connection.close()

print(f"Total efficiency rows: {result.shape[0]}")
print(f"Metrics: {result['metric'].unique().to_list()}")

# ──────────────────────────────────────────────
# STEP 2: COMPUTE POSITION-GROUP AVERAGES
# These serve the same role as "group-level intercepts"
# in the PyMC model — the anchor that low-data players
# get pulled toward. One average per metric × position.
# ──────────────────────────────────────────────
position_avgs = (
    result
    .group_by(["metric", "position_group"])
    .agg([
        pl.col("yards_per_opportunity").mean().alias("position_avg"),
        pl.col("yards_per_opportunity").std().alias("position_std"),
        pl.col("yards_per_opportunity").count().alias("position_n"),
    ])
)
print("\nPosition-group averages:")
print(position_avgs.sort(["metric", "position_group"]))

# ──────────────────────────────────────────────
# STEP 3: COMPUTE PER-PLAYER AVERAGES
# Each player's raw average across all their games,
# plus their game count (which determines how much
# the shrinkage trusts their individual data vs the
# position average).
# ──────────────────────────────────────────────
player_avgs = (
    result
    .group_by(["metric", "gsis_id", "display_name", "position_group"])
    .agg([
        pl.col("yards_per_opportunity").mean().alias("player_avg"),
        pl.col("yards_per_opportunity").std().alias("player_std"),
        pl.col("yards_per_opportunity").count().alias("player_n"),
    ])
)

# ──────────────────────────────────────────────
# STEP 4: APPLY SHRINKAGE
# Blend each player's average with their position average,
# weighted by sample size. The formula:
#
#   shrunk = (player_n * player_avg + k * position_avg) / (player_n + k)
#
# where k controls how many games of data it takes before
# the player's own average dominates. k=10 means a player
# with 10 games is weighted 50/50 between their own data
# and the position average. A player with 50 games is ~83%
# their own data. A player with 2 games is ~17% their own data.
#
# This is the same partial-pooling idea as the PyMC model,
# just computed directly. The k parameter plays the same role
# as player_sigma in the hierarchical model — it controls
# how aggressively low-data players get pulled toward the group.
# ──────────────────────────────────────────────
SHRINKAGE_K = 10  # "equivalent sample size" of the prior

player_shrunk = (
    player_avgs
    .join(position_avgs, on=["metric", "position_group"])
    .with_columns([
        (
            (pl.col("player_n") * pl.col("player_avg") + SHRINKAGE_K * pl.col("position_avg"))
            / (pl.col("player_n") + SHRINKAGE_K)
        ).round(2).alias("shrunk_avg"),
    ])
)

# ──────────────────────────────────────────────
# STEP 5: VERIFY SHRINKAGE IS WORKING
# Compare high-data vs low-data players. High-data players'
# shrunk average should be close to their raw average.
# Low-data players should be pulled toward position average.
# ──────────────────────────────────────────────
print("\n── Shrinkage verification: yards_per_target ──")

# High-data player
high_data = (
    player_shrunk
    .filter(pl.col("metric") == "yards_per_target")
    .sort("player_n", descending=True)
    .head(5)
    .select(["display_name", "position_group", "player_n", "player_avg", "position_avg", "shrunk_avg"])
)
print("\nHigh-data players (should be close to player_avg):")
print(high_data)

# Low-data player
low_data = (
    player_shrunk
    .filter((pl.col("metric") == "yards_per_target") & (pl.col("player_n") <= 3))
    .sort("player_avg", descending=True)
    .head(5)
    .select(["display_name", "position_group", "player_n", "player_avg", "position_avg", "shrunk_avg"])
)
print("\nLow-data players (should be pulled toward position_avg):")
print(low_data)

# ──────────────────────────────────────────────
# STEP 6: COMPUTE RESIDUAL SPREAD PER METRIC
# Same approach as the EPA uncertainty wrapper: measure
# how much individual games deviate from the player's
# shrunk average, and use that spread for simulator draws.
# ──────────────────────────────────────────────
residual_spreads = {}

for metric in result["metric"].unique().to_list():
    metric_data = result.filter(pl.col("metric") == metric)
    metric_shrunk = player_shrunk.filter(pl.col("metric") == metric)

    # Join each game observation with its player's shrunk estimate
    joined = metric_data.join(
        metric_shrunk.select(["gsis_id", "metric", "shrunk_avg"]),
        on=["gsis_id", "metric"],
    )

    residuals = (joined["yards_per_opportunity"] - joined["shrunk_avg"]).to_numpy()
    spread = float(np.std(residuals))
    residual_spreads[metric] = spread

    print(f"\n{metric}:")
    print(f"  Residual std (game-to-game noise): {spread:.2f}")
    print(f"  Residual mean (bias check):        {np.mean(residuals):.4f}")

# ──────────────────────────────────────────────
# STEP 7: DRAW FUNCTIONS FOR THE SIMULATOR
# Same pattern as draw_offense_epa and draw_defense_epa:
# point estimate as center, measured residual spread as noise.
# One draw = one plausible per-game efficiency value.
# ──────────────────────────────────────────────
def draw_efficiency(player_shrunk_avg, metric, rng=None):
    """Draw one plausible per-game efficiency value.

    player_shrunk_avg : the player's shrunk efficiency estimate
    metric            : 'yards_per_target', 'yards_per_carry', or 'yards_per_attempt'
    rng               : optional numpy Generator for reproducibility
    """
    if rng is None:
        rng = np.random.default_rng()
    spread = residual_spreads[metric]
    return max(0, rng.normal(loc=player_shrunk_avg, scale=spread))


# ──────────────────────────────────────────────
# STEP 8: QUICK DEMO
# Show one player's draw distribution to confirm
# the whole pipeline works end to end.
# ──────────────────────────────────────────────
rng = np.random.default_rng(42)

# Pick a known player from the shrunk estimates
demo_player = player_shrunk.filter(
    (pl.col("metric") == "yards_per_target") &
    (pl.col("player_n") > 50)
).sort("player_n", descending=True).head(1)

if demo_player.height > 0:
    name = demo_player["display_name"][0]
    shrunk = demo_player["shrunk_avg"][0]
    raw = demo_player["player_avg"][0]
    n = demo_player["player_n"][0]

    draws = np.array([draw_efficiency(shrunk, "yards_per_target", rng=rng) for _ in range(5000)])

    print(f"\n── Draw demo: {name} (yards_per_target) ──")
    print(f"Games: {n}")
    print(f"Raw avg:    {raw:.2f}")
    print(f"Shrunk avg: {shrunk:.2f}")
    print(f"5000 draws -> mean: {draws.mean():.2f}  std: {draws.std():.2f}")
    print(f"Residual spread:    {residual_spreads['yards_per_target']:.2f}")

# ──────────────────────────────────────────────
# STEP 9: EXPORT SHRUNK ESTIMATES
# Save the shrunk player efficiency table so the
# simulator can load it without recomputing.
# ──────────────────────────────────────────────
output_path = Path(__file__).parent.parent / "data" / "player_efficiency_shrunk.parquet"
output_path.parent.mkdir(parents=True, exist_ok=True)
player_shrunk.write_parquet(output_path)
print(f"\nShrunk estimates saved to {output_path}")