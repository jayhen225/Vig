from pathlib import Path

import duckdb
import polars as pl
import pymc as pm
import numpy as np
import arviz as az

# --- Load training data from DuckDB ---
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "target_share.sql"
sql_query = sql_path.read_text()
result = connection.execute(sql_query).pl()
result = result.filter(pl.col("season") <= 2024)
connection.close()

# --- Create group labels (position + draft tier combined) ---
result = result.with_columns(
    (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
)

# --- Map group labels to integer indices ---
unique_groups = result.select("group_label").unique().sort("group_label").with_row_index("group_idx")
result = result.join(unique_groups, on="group_label")

# --- Map players to integer indices ---
unique_players = result.select("gsis_id").unique().sort("gsis_id").with_row_index("player_idx")
result = result.join(unique_players, on="gsis_id")

# --- Map each player to their group ---
player_to_group = result.select("player_idx", "group_idx").unique().sort("player_idx")

# --- Verify ---
# print(f"Observations: {result.shape[0]}")
# print(f"Groups: {result['group_idx'].n_unique()}")
# print(f"Players: {result['player_idx'].n_unique()}")
# print(result.head(5))

target_share = result["target_share"].to_numpy()
player_idx = result["player_idx"].to_numpy().astype(int)
group_idx = result["group_idx"].to_numpy().astype(int)
player_group = player_to_group["group_idx"].to_numpy().astype(int)

n_groups = result["group_idx"].n_unique()
n_players = result["player_idx"].n_unique()

with pm.Model() as model:
    # Level 1: League-wide average
    league_mu = pm.Normal("league_mu", mu=0.15, sigma=0.05)
    # Level 2: How much groups differ from league average (hyperparameter)
    group_sigma = pm.HalfNormal("group_sigma", sigma=0.05)
    
    # Level 2: Each group's intercept
    group_mu = pm.Normal("group_mu", mu=league_mu, sigma=group_sigma, shape=n_groups)
    # Level 3: How much players differ from their group (hyperparameter)
    player_sigma = pm.HalfNormal("player_sigma", sigma=0.05)
    
    # Level 3: Each player's intercept
    player_mu = pm.Normal("player_mu", mu=group_mu[player_group], sigma=player_sigma, shape=n_players)
    # Level 4: Observation noise — connect model to actual data
    kappa = pm.HalfNormal("kappa", sigma=50)
    
    # Likelihood: observed target shares
    target = pm.Beta("target", mu=pm.math.invlogit(player_mu[player_idx]), nu=kappa, observed=target_share)
    # --- Sample from the posterior ---
    trace = pm.sample(1000, tune=1000, cores=1, random_seed=42)
    trace_path = Path(__file__).parent.parent / "data" / "traces" / "target_share_trace_backtest"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace.to_netcdf(str(trace_path) + ".nc")
    print(f"Trace saved to {trace_path}.nc")
    summary = az.summary(trace, var_names=["league_mu", "group_sigma", "group_mu", "player_sigma", "kappa"])
    print(summary)
    print(unique_groups)