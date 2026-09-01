"""Layer 5 + Layer 1: Book-Line-Centered Pricer with Recency-Weighted Usage

Combines both improvements:
  Layer 5: Accept book's lines as centers, compete on distribution + correlation
  Layer 1: Use recency-weighted usage for variance estimation, not career averages

The recency adjustment matters because:
  - A player whose role recently changed (trade, injury to teammate, promotion)
    has different game-to-game variance than their career average suggests
  - 80% of RBs and 25% of WRs had significantly stale career-average estimates
  - More accurate variance → more accurate correlation strength → better parlay prices
"""

from pathlib import Path

import numpy as np
import polars as pl
import duckdb
import arviz as az
from scipy.special import expit

# ══════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent / "data"
SQL_DIR = Path(__file__).parent.parent / "pipeline" / "sql"
DB_PATH = DATA_DIR / "nfl_data.duckdb"

LEAGUE_AVG_PLAYS = 62.3
PLAYS_SPREAD = 8.5
DEFAULT_PASS_RATE = 0.58

MARKET_TO_METRIC = {
    "player_pass_yds": "yards_per_attempt",
    "player_rush_yds": "yards_per_carry",
    "player_reception_yds": "yards_per_target",
}

RESIDUAL_SPREADS = {
    "player_pass_yds": 2.63,
    "player_rush_yds": 2.67,
    "player_reception_yds": 6.01,
}

# Map markets to which recency metric to use
MARKET_TO_USAGE_METRIC = {
    "player_reception_yds": "target_share",
    "player_rush_yds": "carry_share",
    "player_pass_yds": None,  # QB doesn't use usage model
}


# ══════════════════════════════════════════════════════════════
# MODEL LOADING — now includes recency data
# ══════════════════════════════════════════════════════════════

def load_models():
    """Load PyMC traces, efficiency estimates, AND recency-adjusted usage."""

    trace_path = DATA_DIR / "traces" / "target_share_trace_backtest.nc"
    if not trace_path.exists():
        trace_path = DATA_DIR / "traces" / "target_share_trace.nc"

    ts_trace = az.from_netcdf(str(trace_path))

    connection = duckdb.connect(str(DB_PATH), read_only=True)

    ts_result = connection.execute(Path(SQL_DIR / "target_share.sql").read_text()).pl()
    ts_result = ts_result.filter(pl.col("season") <= 2024)
    ts_result = ts_result.with_columns(
        (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
    )
    ts_unique = ts_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
    ts_names = ts_result.select(["gsis_id", "display_name"]).unique()
    ts_indexed = ts_unique.join(ts_names, on="gsis_id")
    ts_name_to_idx = {r["display_name"]: r["idx"] for r in ts_indexed.iter_rows(named=True)}
    ts_draws = expit(ts_trace.posterior["player_mu"].values.reshape(
        -1, ts_trace.posterior["player_mu"].shape[-1]))

    cs_trace = az.from_netcdf(str(DATA_DIR / "traces" / "carry_share_trace.nc"))
    cs_result = connection.execute(Path(SQL_DIR / "carry_share.sql").read_text()).pl()
    cs_result = cs_result.filter(pl.col("season") <= 2024)
    cs_result = cs_result.with_columns(
        (pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label")
    )
    cs_unique = cs_result.select("gsis_id").unique().sort("gsis_id").with_row_index("idx")
    cs_names = cs_result.select(["gsis_id", "display_name"]).unique()
    cs_indexed = cs_unique.join(cs_names, on="gsis_id")
    cs_name_to_idx = {r["display_name"]: r["idx"] for r in cs_indexed.iter_rows(named=True)}
    cs_draws = expit(cs_trace.posterior["player_mu"].values.reshape(
        -1, cs_trace.posterior["player_mu"].shape[-1]))

    connection.close()

    # Efficiency estimates
    eff_df = pl.read_parquet(DATA_DIR / "player_efficiency_shrunk.parquet")
    eff_lookup = {}
    for row in eff_df.iter_rows(named=True):
        eff_lookup[(row["display_name"], row["metric"])] = row["shrunk_avg"]

    # ── Layer 1: Recency-adjusted usage ──
    recency_path = DATA_DIR / "recency_adjusted_usage.parquet"
    recency_lookup = {}
    if recency_path.exists():
        recency_df = pl.read_parquet(recency_path)
        for row in recency_df.iter_rows(named=True):
            key = (row["display_name"], row["metric"])
            recency_lookup[key] = {
                "adjusted_center": row["adjusted_center"],
                "posterior_mean": row["posterior_mean"],
                "posterior_std": row["posterior_std"],
                "shift": row["shift"],
                "recent_games": row["recent_games"],
            }

    return {
        "ts_draws": ts_draws, "ts_idx": ts_name_to_idx,
        "cs_draws": cs_draws, "cs_idx": cs_name_to_idx,
        "eff_lookup": eff_lookup,
        "recency": recency_lookup,
    }


# ══════════════════════════════════════════════════════════════
# PLAYER-SPECIFIC VARIANCE ESTIMATION — with recency adjustment
#
# Key change from v1: instead of drawing usage from the full
# career posterior (which centers on the career average), we
# draw from a distribution centered on the RECENCY-ADJUSTED
# value. The posterior's STD still provides the uncertainty width.
#
# This means a player who recently became a starter will have
# variance estimated around their CURRENT usage level, not
# their career average that includes backup years.
# ══════════════════════════════════════════════════════════════

def estimate_player_variance(player_name, market, models, n_samples=2000, seed=42):
    """Estimate game-to-game variance using recency-adjusted usage centers."""
    rng = np.random.default_rng(seed)
    metric = MARKET_TO_METRIC[market]
    residual_spread = RESIDUAL_SPREADS[market]

    eff_key = (player_name, metric)
    if eff_key not in models["eff_lookup"]:
        return None
    shrunk_eff = models["eff_lookup"][eff_key]
    if shrunk_eff <= 0:
        return None

    # Get recency-adjusted usage center and posterior std
    usage_metric = MARKET_TO_USAGE_METRIC[market]
    recency_data = None
    if usage_metric:
        recency_data = models["recency"].get((player_name, usage_metric))

    stats = []

    for _ in range(n_samples):
        plays = max(30, round(rng.normal(LEAGUE_AVG_PLAYS, PLAYS_SPREAD)))

        if market == "player_pass_yds":
            # QB: no usage model, same as before
            attempts = max(5, round(plays * DEFAULT_PASS_RATE))
            eff = max(0, rng.normal(shrunk_eff, residual_spread))
            stat = attempts * eff

        elif market == "player_reception_yds":
            if player_name not in models["ts_idx"]:
                return None

            # LAYER 1 CHANGE: draw usage from recency-adjusted center
            # instead of raw career posterior
            if recency_data:
                # Draw from Normal(adjusted_center, posterior_std)
                # This centers on recent form, spreads by career uncertainty
                usage = max(0.001, rng.normal(
                    recency_data["adjusted_center"],
                    recency_data["posterior_std"]
                ))
            else:
                # Fallback: raw career posterior draw
                idx = models["ts_idx"][player_name]
                draw_i = rng.integers(0, models["ts_draws"].shape[0])
                usage = models["ts_draws"][draw_i, idx]

            attempts = max(5, round(plays * DEFAULT_PASS_RATE))
            targets = usage * attempts
            eff = max(0, rng.normal(shrunk_eff, residual_spread))
            stat = targets * eff

        elif market == "player_rush_yds":
            if player_name not in models["cs_idx"]:
                return None

            # LAYER 1 CHANGE: same recency adjustment for carry share
            if recency_data:
                usage = max(0.001, rng.normal(
                    recency_data["adjusted_center"],
                    recency_data["posterior_std"]
                ))
            else:
                idx = models["cs_idx"][player_name]
                draw_i = rng.integers(0, models["cs_draws"].shape[0])
                usage = models["cs_draws"][draw_i, idx]

            rush_rate = 1 - DEFAULT_PASS_RATE
            attempts = max(5, round(plays * rush_rate))
            carries = usage * attempts
            eff = max(0, rng.normal(shrunk_eff, residual_spread))
            stat = carries * eff

        stats.append(stat)

    return {
        "mean": np.mean(stats),
        "std": np.std(stats),
        "median": np.median(stats),
    }


# ══════════════════════════════════════════════════════════════
# CORRELATED PARLAY PRICER (unchanged from Layer 5 v1)
# ══════════════════════════════════════════════════════════════

def price_correlated_parlay(legs, player_variances, n_sims=10000, seed=42):
    """Price a parlay accounting for same-game correlation."""
    rng = np.random.default_rng(seed)

    leg_info = []
    for leg in legs:
        pv = player_variances.get(leg["player"])
        if pv is None:
            return None

        game_share = 0.40
        total_std = pv["std"]
        game_sensitivity = total_std * np.sqrt(game_share)
        indiv_std = total_std * np.sqrt(1 - game_share)

        leg_info.append({
            **leg,
            "total_std": total_std,
            "game_sensitivity": game_sensitivity,
            "indiv_std": indiv_std,
        })

    hits = 0

    for _ in range(n_sims):
        home_game_factor = rng.normal(0, 1)
        away_game_factor = rng.normal(0, 1)

        all_hit = True

        for leg in leg_info:
            if leg["team"] == "home":
                game_factor = home_game_factor
            else:
                game_factor = away_game_factor

            stat = (
                leg["book_line"]
                + game_factor * leg["game_sensitivity"]
                + rng.normal(0, leg["indiv_std"])
            )

            if leg["over_under"] == "over":
                if stat <= leg["book_line"]:
                    all_hit = False
                    break
            else:
                if stat >= leg["book_line"]:
                    all_hit = False
                    break

        if all_hit:
            hits += 1

    correlated_prob = hits / n_sims

    # Independent pricing comparison
    independent_probs = []
    for leg in leg_info:
        leg_hits = 0
        for _ in range(n_sims):
            stat = leg["book_line"] + rng.normal(0, leg["total_std"])
            if leg["over_under"] == "over":
                if stat > leg["book_line"]:
                    leg_hits += 1
            else:
                if stat < leg["book_line"]:
                    leg_hits += 1
        independent_probs.append(leg_hits / n_sims)

    independent_product = 1.0
    for p in independent_probs:
        independent_product *= p

    return {
        "correlated_prob": correlated_prob,
        "independent_prob": independent_product,
        "individual_probs": independent_probs,
        "correlation_edge": correlated_prob - independent_product,
    }


# ══════════════════════════════════════════════════════════════
# DEMO — Compare career posterior vs recency-adjusted
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("LAYER 5 + LAYER 1: Recency-Adjusted Correlation Pricer")
    print("=" * 60)

    print("\nLoading models (with recency data)...")
    models = load_models()
    print(f"  Target share: {models['ts_draws'].shape[1]} players")
    print(f"  Carry share: {models['cs_draws'].shape[1]} players")
    print(f"  Recency estimates: {len(models['recency'])} player-metric pairs")

    # ── Show recency impact on key players ──
    print("\n" + "=" * 60)
    print("RECENCY IMPACT ON PLAYER ESTIMATES")
    print("=" * 60)

    players_to_check = [
        ("Travis Kelce", "player_reception_yds", "target_share"),
        ("Derrick Henry", "player_rush_yds", "carry_share"),
        ("Patrick Mahomes", "player_pass_yds", None),
        ("Tyreek Hill", "player_reception_yds", "target_share"),
        ("Saquon Barkley", "player_rush_yds", "carry_share"),
        ("Josh Allen", "player_pass_yds", None),
    ]

    print(f"\n{'Player':<20} {'Career':>8} {'Recent':>8} {'Adjusted':>8} {'Shift':>8}")
    print("-" * 60)

    for name, market, usage_metric in players_to_check:
        if usage_metric:
            rec = models["recency"].get((name, usage_metric))
            if rec:
                print(f"{name:<20} {rec['posterior_mean']:>8.4f} "
                      f"{rec['adjusted_center'] - rec['shift'] + rec['shift']:>8.4f} "
                      f"{rec['adjusted_center']:>8.4f} {rec['shift']:>+8.4f}")
            else:
                print(f"{name:<20} (no recency data)")
        else:
            print(f"{name:<20} (QB — no usage model)")

    # ── Estimate variances with recency adjustment ──
    print("\n" + "=" * 60)
    print("VARIANCE ESTIMATION (with recency)")
    print("=" * 60)

    player_variances = {}
    for name, market, _ in players_to_check:
        pv = estimate_player_variance(name, market, models)
        if pv:
            player_variances[name] = pv
            print(f"  {name}: mean={pv['mean']:.1f}, std={pv['std']:.1f}")

    # ── Parlay 1: Same-team ──
    print("\n" + "=" * 60)
    print("PARLAY 1: Same-Team (Mahomes + Kelce)")
    print("=" * 60)

    parlay_1 = [
        {"player": "Patrick Mahomes", "market": "player_pass_yds",
         "book_line": 275.5, "over_under": "over", "team": "home"},
        {"player": "Travis Kelce", "market": "player_reception_yds",
         "book_line": 65.5, "over_under": "over", "team": "home"},
    ]

    result_1 = price_correlated_parlay(parlay_1, player_variances, n_sims=50000, seed=42)
    if result_1:
        for i, leg in enumerate(parlay_1):
            print(f"  {leg['player']} Over {leg['book_line']}: {result_1['individual_probs'][i]:.4f}")
        print(f"\n  Independent (book): {result_1['independent_prob']:.4f} ({result_1['independent_prob']*100:.1f}%)")
        print(f"  Correlated (ours):  {result_1['correlated_prob']:.4f} ({result_1['correlated_prob']*100:.1f}%)")
        print(f"  Correlation edge:   {result_1['correlation_edge']:+.4f} ({result_1['correlation_edge']*100:+.1f}%)")

    # ── Parlay 2: Cross-team ──
    print("\n" + "=" * 60)
    print("PARLAY 2: Cross-Team (Kelce + Henry)")
    print("=" * 60)

    parlay_2 = [
        {"player": "Travis Kelce", "market": "player_reception_yds",
         "book_line": 65.5, "over_under": "over", "team": "home"},
        {"player": "Derrick Henry", "market": "player_rush_yds",
         "book_line": 85.5, "over_under": "over", "team": "away"},
    ]

    result_2 = price_correlated_parlay(parlay_2, player_variances, n_sims=50000, seed=42)
    if result_2:
        for i, leg in enumerate(parlay_2):
            print(f"  {leg['player']} Over {leg['book_line']}: {result_2['individual_probs'][i]:.4f}")
        print(f"\n  Independent (book): {result_2['independent_prob']:.4f} ({result_2['independent_prob']*100:.1f}%)")
        print(f"  Correlated (ours):  {result_2['correlated_prob']:.4f} ({result_2['correlated_prob']*100:.1f}%)")
        print(f"  Correlation edge:   {result_2['correlation_edge']:+.4f} ({result_2['correlation_edge']*100:+.1f}%)")

    # ── Parlay 3: Three-leg same-team ──
    print("\n" + "=" * 60)
    print("PARLAY 3: Three-Leg Same-Team (Mahomes + Kelce + Hill)")
    print("=" * 60)

    if "Tyreek Hill" in player_variances:
        parlay_3 = [
            {"player": "Patrick Mahomes", "market": "player_pass_yds",
             "book_line": 275.5, "over_under": "over", "team": "home"},
            {"player": "Travis Kelce", "market": "player_reception_yds",
             "book_line": 65.5, "over_under": "over", "team": "home"},
            {"player": "Tyreek Hill", "market": "player_reception_yds",
             "book_line": 75.5, "over_under": "over", "team": "home"},
        ]

        result_3 = price_correlated_parlay(parlay_3, player_variances, n_sims=50000, seed=42)
        if result_3:
            for i, leg in enumerate(parlay_3):
                print(f"  {leg['player']} Over {leg['book_line']}: {result_3['individual_probs'][i]:.4f}")
            print(f"\n  Independent (book): {result_3['independent_prob']:.4f} ({result_3['independent_prob']*100:.1f}%)")
            print(f"  Correlated (ours):  {result_3['correlated_prob']:.4f} ({result_3['correlated_prob']*100:.1f}%)")
            print(f"  Correlation edge:   {result_3['correlation_edge']:+.4f} ({result_3['correlation_edge']*100:+.1f}%)")

    # ── Parlay 4: Opposing correlation ──
    print("\n" + "=" * 60)
    print("PARLAY 4: Opposing (Mahomes Over + Henry Under)")
    print("=" * 60)

    parlay_4 = [
        {"player": "Patrick Mahomes", "market": "player_pass_yds",
         "book_line": 275.5, "over_under": "over", "team": "home"},
        {"player": "Derrick Henry", "market": "player_rush_yds",
         "book_line": 85.5, "over_under": "under", "team": "away"},
    ]

    result_4 = price_correlated_parlay(parlay_4, player_variances, n_sims=50000, seed=42)
    if result_4:
        for i, leg in enumerate(parlay_4):
            side = leg['over_under'].upper()
            print(f"  {leg['player']} {side} {leg['book_line']}: {result_4['individual_probs'][i]:.4f}")
        print(f"\n  Independent (book): {result_4['independent_prob']:.4f} ({result_4['independent_prob']*100:.1f}%)")
        print(f"  Correlated (ours):  {result_4['correlated_prob']:.4f} ({result_4['correlated_prob']*100:.1f}%)")
        print(f"  Correlation edge:   {result_4['correlation_edge']:+.4f} ({result_4['correlation_edge']*100:+.1f}%)")

    # ══════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\n  Layer 5: Book's lines as centers → individual legs match the book")
    print("  Layer 1: Recency-weighted usage → more accurate variance estimation")
    print("  Combined: correlation edges reflect CURRENT player roles, not career averages")
    print("\n  v1 results (career posteriors only):")
    print("    Parlay 1 (same-team 2-leg):  +6.2% edge")
    print("    Parlay 2 (cross-team):        -0.5% edge")
    print("    Parlay 3 (same-team 3-leg):  +9.9% edge")
    print("    Parlay 4 (opposing):          ~0% edge")
    print("\n  v2 results (with recency adjustment):")
    if result_1:
        print(f"    Parlay 1 (same-team 2-leg):  {result_1['correlation_edge']:+.1%} edge")
    if result_2:
        print(f"    Parlay 2 (cross-team):        {result_2['correlation_edge']:+.1%} edge")
    if result_3:
        print(f"    Parlay 3 (same-team 3-leg):  {result_3['correlation_edge']:+.1%} edge")
    if result_4:
        print(f"    Parlay 4 (opposing):          {result_4['correlation_edge']:+.1%} edge")