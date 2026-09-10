from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import polars as pl

trace = az.from_netcdf("data/traces/target_share_trace.nc")

# Load training data (same setup as train_model.py)
connection = duckdb.connect(str(Path(__file__).parent.parent / "data" / "nfl_data.duckdb"), read_only=True)
sql_path = Path(__file__).parent / "sql" / "target_share.sql"
result = connection.execute(sql_path.read_text()).pl()
connection.close()

result = result.with_columns(
    (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
)
unique_groups = result.select("group_label").unique().sort("group_label").with_row_index("group_idx")
result = result.join(unique_groups, on="group_label")
unique_players = result.select("gsis_id").unique().sort("gsis_id").with_row_index("player_idx")
result = result.join(unique_players, on="gsis_id")

# Pick a player
player_name = "Devin Funchess"
player_rows = result.filter(pl.col("display_name") == player_name)
idx = player_rows["player_idx"][0]

# Raw average from actual games
raw_avg = player_rows["target_share"].mean()
n_games = player_rows.height

# Group average
group = player_rows["group_label"][0]
group_idx_val = player_rows["group_idx"][0]

# Extract posterior draws for this player (on logit scale)
player_draws = trace.posterior["player_mu"].values[:, :, idx].flatten()

# Transform from logit scale to probability (0-1)
from scipy.special import expit

player_target_share_draws = expit(player_draws)

print(f"Player: {player_name}")
print(f"Group: {group}")
print(f"Games: {n_games}")
print(f"Raw average target share: {raw_avg:.4f}")
print(f"Posterior mean: {player_target_share_draws.mean():.4f}")
print(f"Posterior 89% interval: [{np.percentile(player_target_share_draws, 5.5):.4f}, {np.percentile(player_target_share_draws, 94.5):.4f}]")

# few_games = result.group_by("display_name", "group_label").agg(
#     pl.col("target_share").count().alias("n_games"),
#     pl.col("target_share").mean().alias("raw_avg")
# ).filter(pl.col("n_games") <= 5).sort("raw_avg", descending=True).head(10)
# print(few_games)
# high volume vet Chase
# rookie with a few games egbuka
# player whos average differes from group shakir
