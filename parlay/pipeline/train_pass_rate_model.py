from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import polars as pl
import pymc as pm

# ──────────────────────────────────────────────
# DATA LOADING
# Connect to DuckDB, run the pass rate query,
# get one row per team per game with pass_rate
# ──────────────────────────────────────────────
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "pass_rate.sql"
result = connection.execute(sql_path.read_text()).pl()
connection.close()

# ──────────────────────────────────────────────
# INDEX PREPARATION
# PyMC needs integer indices, not string labels.
# Only one grouping level: team × season
# ──────────────────────────────────────────────
result = result.with_columns(
    (pl.col("team") + "_" + pl.col("season").cast(str)).alias("team_season_label")
)

unique_team_seasons = (
    result.select("team_season_label")
    .unique()
    .sort("team_season_label")
    .with_row_index("team_season_idx")
)
result = result.join(unique_team_seasons, on="team_season_label")

# ──────────────────────────────────────────────
# EXTRACT ARRAYS FOR PYMC
# pass_rate: the observed data (what actually happened)
# team_season_idx: which team-season each game belongs to
# n_team_seasons: how many parameters to create
# ──────────────────────────────────────────────
pass_rate = result["pass_rate"].to_numpy()
team_season_idx = result["team_season_idx"].to_numpy().astype(int)
n_team_seasons = result["team_season_idx"].n_unique()

# Beta distribution can't handle exact 0.0 or 1.0
eps = 1e-6
pass_rate = np.clip(pass_rate, eps, 1 - eps)

# ──────────────────────────────────────────────
# VERIFY
# Sanity check before modeling
# ──────────────────────────────────────────────
print(f"Observations: {result.shape[0]}")
print(f"Team-seasons: {n_team_seasons}")
print(f"Pass rate range: {pass_rate.min():.4f} - {pass_rate.max():.4f}")

# ──────────────────────────────────────────────
# MODEL
# Two-level hierarchy:
#   Level 1: league-wide average pass rate
#   Level 2: each team-season deviates from that
#
# Simpler than target/carry share because there's
# no player level — we're estimating a team-level
# property (scheme), not individual player usage.
# ──────────────────────────────────────────────
with pm.Model() as model:
    # League-wide average pass rate (on logit scale)
    # mu=0.0 on logit scale = invlogit(0) = 0.50, a neutral starting point
    # sigma=0.5 is wide enough to let data drive the answer
    league_mu = pm.Normal("league_mu", mu=0.0, sigma=0.5)

    # How much team-seasons differ from the league average
    # This is the hyperparameter that controls shrinkage —
    # if team-seasons are very similar, early-season estimates
    # get pulled hard toward the league average
    team_season_sigma = pm.HalfNormal("team_season_sigma", sigma=0.5)

    # Each team-season's underlying pass rate
    # Drawn from a distribution centered at the league average
    # with spread controlled by team_season_sigma
    team_season_mu = pm.Normal(
        "team_season_mu",
        mu=league_mu,
        sigma=team_season_sigma,
        shape=n_team_seasons
    )

    # Game-to-game noise concentration
    # Controls how tightly individual games cluster around
    # the team-season's true pass rate
    kappa = pm.HalfNormal("kappa", sigma=50)

    # Likelihood: connect model to observed data
    # invlogit transforms from logit scale to 0-1 range for Beta
    # team_season_idx maps each game to its team-season parameter
    observed = pm.Beta(
        "observed",
        mu=pm.math.invlogit(team_season_mu[team_season_idx]),
        nu=kappa,
        observed=pass_rate
    )

    # ──────────────────────────────────────────────
    # SAMPLE
    # Draw from the posterior — should be faster than
    # the player-level models since fewer parameters
    # (~224 team-seasons vs ~1,123 players)
    # ──────────────────────────────────────────────
    trace = pm.sample(1000, tune=1000, cores=1, random_seed=42)

    # ──────────────────────────────────────────────
    # SAVE
    # Store trace to disk so we don't re-sample every time
    # ──────────────────────────────────────────────
    trace_path = Path(__file__).parent.parent / "data" / "traces" / "pass_rate_trace"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace.to_netcdf(str(trace_path) + ".nc")
    print(f"Trace saved to {trace_path}.nc")

    # ──────────────────────────────────────────────
    # DIAGNOSTICS
    # Check convergence — r_hat near 1.0 means
    # the chains agreed with each other
    # ──────────────────────────────────────────────
    summary = az.summary(trace, var_names=["league_mu", "team_season_sigma", "kappa"])
    print(summary)
    print("\nTeam-seasons mapped:")
    print(unique_team_seasons.head(10))