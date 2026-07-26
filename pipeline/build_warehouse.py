import polars as pl
import duckdb
from pathlib import Path

connection = duckdb.connect(Path(__file__).parent.parent / "data" / "nfl_data.duckdb")

parquet_dir = Path(__file__).parent.parent / "data" / "raw"
parquet_list = list(parquet_dir.rglob("*.parquet"))

print(len(parquet_list))

for file in parquet_list:
    table_name = file.stem
    print(f"Loading {file} into table {table_name}")
    connection.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet('{file}')")
    #print(file.stem)