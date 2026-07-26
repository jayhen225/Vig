import nflreadpy as nfl
import polars as pl
import duckdb
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEASONS = list(range(2019, 2026))

def pull_and_save(dataset_name, loader, *args, **kwargs):
    nfl_data = loader(*args, **kwargs)
    print(nfl_data.shape)
    nfl_data.write_parquet(DATA_DIR / f"{dataset_name}.parquet")

pull_configs = [{ "dataset_name": "pbp_data", "loader": nfl.load_pbp, "kwargs": {"seasons": SEASONS} },
                  { "dataset_name": "roster_data", "loader": nfl.load_rosters, "kwargs": {"seasons": SEASONS} },
                  { "dataset_name": "schedule_data", "loader": nfl.load_schedules, "kwargs": {"seasons": SEASONS} },
                  { "dataset_name": "next_gen_data", "loader": nfl.load_nextgen_stats, "kwargs": {"seasons": SEASONS} },
                  { "dataset_name": "snapcount_data", "loader": nfl.load_snap_counts, "kwargs": {"seasons": SEASONS}  },
                  { "dataset_name": "depth_chart_data", "loader": nfl.load_depth_charts, "kwargs": {"seasons": SEASONS}  },
                  { "dataset_name": "injury_data", "loader": nfl.load_injuries, "kwargs": {"seasons": SEASONS}  },
                  { "dataset_name": "players_data", "loader": nfl.load_players, "kwargs": {}  }]
for config in pull_configs:
    pull_and_save(config["dataset_name"], config["loader"], **config["kwargs"])
def main():
    #def main():
        
    #   DATA_DIR.mkdir(parents=True, exist_ok=True)
    #  pbp = nfl.load_pbp()
    # print(pbp.shape[1])
    #pbp.write_parquet(DATA_DIR / "pbp.parquet")
    #print(f"Saved to {(DATA_DIR / 'pbp.parquet').resolve()}")

 if __name__ == "__main__":
  main()    