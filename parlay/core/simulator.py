"""Game-summary Monte Carlo simulator for pricing parlays.

Connects every model in the project into one simulation chain:
  PyMC posteriors (usage) → efficiency estimates → team scoring → bet resolution

One simulation = one plausible game outcome (team scores + player stats).
Run 10,000 simulations = a distribution of outcomes.
The fraction where a parlay hits = the fair probability for that parlay.

Correlation between legs emerges naturally: all legs in the same game
are resolved against the SAME simulated outcome. If the offense has a
great game, the QB's passing yards go up AND the team's score goes up
AND the receivers' stats go up — all from the same underlying draws.
"""

from pathlib import Path

import arviz as az
import duckdb
import numpy as np
import polars as pl
from scipy.special import expit

# ══════════════════════════════════════════════════════════════
# CONSTANTS — derived from analysis earlier in this project
# ══════════════════════════════════════════════════════════════

# League average points per team per game (from schedule_data)
LEAGUE_AVG_POINTS = 22.92

# League average plays per team per game, and game-to-game spread
LEAGUE_AVG_PLAYS = 62.3
PLAYS_SPREAD = 8.5

# Defensive EPA: league average + calibrated noise
# (defense model showed no signal over naive baseline,
# so we use league avg as center with measured spread)
LEAGUE_AVG_DEF_EPA = 0.0024
DEF_EPA_SPREAD = 0.2170

# Offensive EPA: residual spread from the LightGBM model
# (model barely beat naive, but center point uses team's
# rolling average when available, league avg otherwise)
OFF_EPA_SPREAD = 0.2091

# Default pass rate when team-specific data isn't available
DEFAULT_PASS_RATE = 0.58

# ══════════════════════════════════════════════════════════════
# DATA LOADING
# All loading happens once at startup. The simulation loop
# only touches numpy arrays — no DB queries, no disk IO.
# ══════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent / "data"
SQL_DIR = Path(__file__).parent.parent / "pipeline" / "sql"


def load_trace_with_index(trace_path, sql_path, db_path, id_col, label_col, label_expr, position_filter=None):
    """Load a PyMC trace and rebuild its player/group index mapping.

    Returns the raw posterior draws (on logit scale) and a mapping
    from display_name to integer index, built the same way as the
    training script to ensure consistency.
    """
    # Load trace
    trace = az.from_netcdf(str(trace_path))

    # Rebuild index mapping from the same SQL + sorting used in training
    connection = duckdb.connect(str(db_path), read_only=True)
    result = connection.execute(Path(sql_path).read_text()).pl()
    connection.close()

    # Recreate the label column and index mapping
    result = result.with_columns(label_expr)

    unique = (
        result.select(id_col).unique().sort(id_col).with_row_index("idx")
    )

    # Build name-to-index lookup
    name_mapping = result.select([id_col, "display_name"]).unique()
    indexed = unique.join(name_mapping, on=id_col)

    name_to_idx = {
        row["display_name"]: row["idx"]
        for row in indexed.iter_rows(named=True)
    }

    return trace, name_to_idx


def load_target_share_model():
    """Load target share trace + player name -> index mapping."""
    trace, name_to_idx = load_trace_with_index(
        trace_path=DATA_DIR / "traces" / "target_share_trace.nc",
        sql_path=SQL_DIR / "target_share.sql",
        db_path=DATA_DIR / "nfl_data.duckdb",
        id_col="gsis_id",
        label_col="group_label",
        label_expr=(pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label"),
    )
    # Extract draws: shape (n_draws, n_players), transformed from logit to 0-1
    draws = expit(trace.posterior["player_mu"].values.reshape(-1, trace.posterior["player_mu"].shape[-1]))
    return draws, name_to_idx


def load_carry_share_model():
    """Load carry share trace + player name -> index mapping."""
    trace, name_to_idx = load_trace_with_index(
        trace_path=DATA_DIR / "traces" / "carry_share_trace.nc",
        sql_path=SQL_DIR / "carry_share.sql",
        db_path=DATA_DIR / "nfl_data.duckdb",
        id_col="gsis_id",
        label_col="group_label",
        label_expr=(pl.col("position_group") + "_" + pl.col("draft_tier")).alias("group_label"),
    )
    draws = expit(trace.posterior["player_mu"].values.reshape(-1, trace.posterior["player_mu"].shape[-1]))
    return draws, name_to_idx


def load_efficiency_data():
    """Load shrunk per-player efficiency estimates.

    Returns a dict: (player_name, metric) -> shrunk_avg
    """
    path = DATA_DIR / "player_efficiency_shrunk.parquet"
    df = pl.read_parquet(path)

    lookup = {}
    for row in df.iter_rows(named=True):
        key = (row["display_name"], row["metric"])
        lookup[key] = row["shrunk_avg"]

    # Also compute position-level fallbacks for unknown players
    position_avgs = {}
    for row in df.group_by(["metric", "position_group"]).agg(
        pl.col("shrunk_avg").mean().alias("avg")
    ).iter_rows(named=True):
        position_avgs[(row["position_group"], row["metric"])] = row["avg"]

    return lookup, position_avgs


def load_residual_spreads():
    """Load the measured game-to-game noise per efficiency metric.

    These were computed in build_player_efficiency.py.
    Hardcoded here since they're stable constants derived from
    7 seasons of data, not parameters that change weekly.
    """
    return {
        "yards_per_target": 6.85,
        "yards_per_carry": 2.67,
        "yards_per_attempt": 2.63,
    }


# ══════════════════════════════════════════════════════════════
# DRAW FUNCTIONS
# Each returns one plausible value for one simulation.
# Called once per team or player per simulation.
# ══════════════════════════════════════════════════════════════

def draw_play_count(rng, team_avg=LEAGUE_AVG_PLAYS):
    """One plausible play count for a team in one game."""
    return max(30, round(rng.normal(loc=team_avg, scale=PLAYS_SPREAD)))


def draw_offense_epa(rng, team_rolling_epa=0.0):
    """One plausible offensive EPA/play.

    Uses team's rolling average as center when available,
    falls back to 0.0 (league average) otherwise.
    """
    return rng.normal(loc=team_rolling_epa, scale=OFF_EPA_SPREAD)


def draw_defense_epa(rng):
    """One plausible defensive EPA/play allowed.

    No team-specific model — uses league average + calibrated noise,
    since the defensive model showed no improvement over naive.
    """
    return rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=DEF_EPA_SPREAD)


def draw_usage(draws_array, player_idx, rng):
    """One plausible usage value (target share or carry share)
    drawn from the player's PyMC posterior.

    Picks one random draw from the ~2000 posterior samples.
    """
    n_draws = draws_array.shape[0]
    draw_idx = rng.integers(0, n_draws)
    return draws_array[draw_idx, player_idx]


def draw_efficiency(shrunk_avg, metric, residual_spreads, rng):
    """One plausible per-game efficiency value.

    Center = player's shrunk estimate, spread = measured game-to-game noise.
    """
    spread = residual_spreads[metric]
    return max(0, rng.normal(loc=shrunk_avg, scale=spread))


# ══════════════════════════════════════════════════════════════
# GAME SIMULATION
# Combines all draws into one coherent simulated game.
# ══════════════════════════════════════════════════════════════

def simulate_game(rng, home_rolling_epa=0.0, away_rolling_epa=0.0,
                  home_pass_rate=DEFAULT_PASS_RATE, away_pass_rate=DEFAULT_PASS_RATE):
    """Simulate one complete game at the team level.

    Returns a dict with team scores, play counts, and pass/rush splits
    that player-level stats will be computed from.

    The correlation mechanism: both teams' stats come from the SAME
    set of draws. A simulation where Team A's offense draws high EPA
    produces high Team A scores, high QB passing yards, and high
    receiver stats — all correlated because they share the same draw.
    """
    # --- Team A (home) ---
    home_off_epa = draw_offense_epa(rng, home_rolling_epa)
    away_def_epa = draw_defense_epa(rng)

    # Matchup EPA: offense quality + how much the opposing defense allows
    # Both are deviations from league average, so they add
    home_matchup_epa = home_off_epa + away_def_epa

    home_plays = draw_play_count(rng)
    home_pass_attempts = max(5, round(home_plays * home_pass_rate))
    home_rush_attempts = home_plays - home_pass_attempts

    # EPA -> points: baseline + (EPA/play × plays)
    # EPA is "expected points added" per play, so this conversion is direct
    home_points = max(0, round(LEAGUE_AVG_POINTS + (home_matchup_epa * home_plays)))

    # --- Team B (away) ---
    away_off_epa = draw_offense_epa(rng, away_rolling_epa)
    home_def_epa = draw_defense_epa(rng)

    away_matchup_epa = away_off_epa + home_def_epa

    away_plays = draw_play_count(rng)
    away_pass_attempts = max(5, round(away_plays * away_pass_rate))
    away_rush_attempts = away_plays - away_pass_attempts

    away_points = max(0, round(LEAGUE_AVG_POINTS + (away_matchup_epa * away_plays)))

    return {
        "home_score": home_points,
        "away_score": away_points,
        "home_pass_attempts": home_pass_attempts,
        "home_rush_attempts": home_rush_attempts,
        "away_pass_attempts": away_pass_attempts,
        "away_rush_attempts": away_rush_attempts,
    }


def simulate_player_stat(rng, player_name, stat_type,
                         usage_draws, usage_name_to_idx,
                         efficiency_lookup, position_avgs,
                         residual_spreads, team_attempts):
    """Simulate one player's stat line for one game.

    Chains: usage draw × team attempts × efficiency draw = stat total.

    player_name   : display name (e.g. "Travis Kelce")
    stat_type     : "receiving_yards", "rushing_yards", or "passing_yards"
    usage_draws   : the posterior draws array (target_share or carry_share)
    usage_name_to_idx : name -> index mapping for the usage trace
    team_attempts : number of team pass/rush attempts in this simulation
    """

    if stat_type == "receiving_yards":
        metric = "yards_per_target"
        # Usage = target share (fraction of team passes thrown to this player)
        if player_name not in usage_name_to_idx:
            return 0.0
        player_idx = usage_name_to_idx[player_name]
        usage = draw_usage(usage_draws, player_idx, rng)
        opportunities = usage * team_attempts

    elif stat_type == "rushing_yards":
        metric = "yards_per_carry"
        if player_name not in usage_name_to_idx:
            return 0.0
        player_idx = usage_name_to_idx[player_name]
        usage = draw_usage(usage_draws, player_idx, rng)
        opportunities = usage * team_attempts

    elif stat_type == "passing_yards":
        metric = "yards_per_attempt"
        # QB doesn't use a "usage" model — they get all pass attempts
        opportunities = team_attempts

    else:
        raise ValueError(f"Unknown stat_type: {stat_type}")

    # Look up efficiency: player-specific shrunk avg, or position fallback
    eff_key = (player_name, metric)
    if eff_key in efficiency_lookup:
        shrunk_avg = efficiency_lookup[eff_key]
    else:
        # Fallback to position average (would need position info —
        # for simplicity, use the overall metric average)
        shrunk_avg = sum(v for (n, m), v in efficiency_lookup.items() if m == metric) / max(1, sum(1 for (n, m) in efficiency_lookup if m == metric))

    # Draw one plausible efficiency value
    eff = draw_efficiency(shrunk_avg, metric, residual_spreads, rng)

    # Final stat = opportunities × efficiency
    return max(0, opportunities * eff)


# ══════════════════════════════════════════════════════════════
# PARLAY PRICING
# The payoff: run N simulations, resolve every leg against each
# simulated outcome, count how often the full parlay hits.
# ══════════════════════════════════════════════════════════════

def price_parlay(legs, n_sims=10000, seed=42,
                 home_rolling_epa=0.0, away_rolling_epa=0.0,
                 home_pass_rate=DEFAULT_PASS_RATE,
                 away_pass_rate=DEFAULT_PASS_RATE,
                 target_share_draws=None, target_share_idx=None,
                 carry_share_draws=None, carry_share_idx=None,
                 efficiency_lookup=None, position_avgs=None,
                 residual_spreads=None):
    """Price a parlay by Monte Carlo simulation.

    legs : list of dicts, each describing one leg:
        {"type": "spread", "team": "KC", "side": "home", "spread": -3.5}
        {"type": "moneyline", "team": "KC", "side": "home"}
        {"type": "prop", "player": "Travis Kelce", "stat": "receiving_yards",
         "line": 65.5, "over_under": "over", "side": "home"}

    Returns: dict with hit_rate (fair probability), hits, total sims
    """
    rng = np.random.default_rng(seed)
    hits = 0

    for _ in range(n_sims):
        # --- Simulate the game ---
        game = simulate_game(
            rng,
            home_rolling_epa=home_rolling_epa,
            away_rolling_epa=away_rolling_epa,
            home_pass_rate=home_pass_rate,
            away_pass_rate=away_pass_rate,
        )

        # --- Resolve each leg ---
        all_legs_hit = True

        for leg in legs:
            if leg["type"] == "spread":
                if leg["side"] == "home":
                    margin = game["home_score"] - game["away_score"]
                else:
                    margin = game["away_score"] - game["home_score"]

                # spread + margin > 0 means covered (same logic as resolve_spread_leg)
                covered = margin + leg["spread"]
                if covered <= 0:  # loss or push = parlay doesn't hit
                    all_legs_hit = False
                    break

            elif leg["type"] == "moneyline":
                if leg["side"] == "home":
                    if game["home_score"] <= game["away_score"]:
                        all_legs_hit = False
                        break
                else:
                    if game["away_score"] <= game["home_score"]:
                        all_legs_hit = False
                        break

            elif leg["type"] == "prop":
                # Determine which team's attempts to use
                if leg["side"] == "home":
                    pass_attempts = game["home_pass_attempts"]
                    rush_attempts = game["home_rush_attempts"]
                else:
                    pass_attempts = game["away_pass_attempts"]
                    rush_attempts = game["away_rush_attempts"]

                # Pick the right usage model and attempt count
                if leg["stat"] == "receiving_yards":
                    usage_draws = target_share_draws
                    usage_idx = target_share_idx
                    attempts = pass_attempts
                elif leg["stat"] == "rushing_yards":
                    usage_draws = carry_share_draws
                    usage_idx = carry_share_idx
                    attempts = rush_attempts
                elif leg["stat"] == "passing_yards":
                    usage_draws = None
                    usage_idx = None
                    attempts = pass_attempts
                else:
                    raise ValueError(f"Unknown prop stat: {leg['stat']}")

                # Simulate the player's stat
                sim_stat = simulate_player_stat(
                    rng=rng,
                    player_name=leg["player"],
                    stat_type=leg["stat"],
                    usage_draws=usage_draws,
                    usage_name_to_idx=usage_idx or {},
                    efficiency_lookup=efficiency_lookup,
                    position_avgs=position_avgs,
                    residual_spreads=residual_spreads,
                    team_attempts=attempts,
                )

                # Resolve: did the prop hit?
                if leg["over_under"] == "over":
                    if sim_stat <= leg["line"]:
                        all_legs_hit = False
                        break
                else:  # under
                    if sim_stat >= leg["line"]:
                        all_legs_hit = False
                        break

        if all_legs_hit:
            hits += 1

    hit_rate = hits / n_sims

    return {
        "hit_rate": hit_rate,
        "hits": hits,
        "total_sims": n_sims,
        "implied_odds": round(-100 * hit_rate / (1 - hit_rate)) if hit_rate > 0.5
                        else round(100 * (1 - hit_rate) / hit_rate) if hit_rate > 0
                        else None,
    }


# ══════════════════════════════════════════════════════════════
# DEMO — Price a real parlay
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Loading models...")

    # Load all models and data
    target_share_draws, target_share_idx = load_target_share_model()
    carry_share_draws, carry_share_idx = load_carry_share_model()
    efficiency_lookup, position_avgs = load_efficiency_data()
    residual_spreads = load_residual_spreads()

    print(f"Target share model: {target_share_draws.shape[1]} players, {target_share_draws.shape[0]} draws")
    print(f"Carry share model: {carry_share_draws.shape[1]} players, {carry_share_draws.shape[0]} draws")
    print(f"Efficiency estimates: {len(efficiency_lookup)} player-metric pairs")

    # ── Define a sample parlay ──
    # Chiefs (home) vs Ravens (away)
    # Leg 1: Travis Kelce Over 65.5 receiving yards (prop)
    # Leg 2: Derrick Henry Over 85.5 rushing yards (prop)
    # Leg 3: Chiefs -3.5 (spread)
    parlay_legs = [
        {
            "type": "prop",
            "player": "Travis Kelce",
            "stat": "receiving_yards",
            "line": 65.5,
            "over_under": "over",
            "side": "home",
        },
        {
            "type": "prop",
            "player": "Derrick Henry",
            "stat": "rushing_yards",
            "line": 85.5,
            "over_under": "over",
            "side": "away",
        },
        {
            "type": "spread",
            "team": "KC",
            "side": "home",
            "spread": -3.5,
        },
    ]

    print("\n── Pricing parlay ──")
    print("Legs:")
    for i, leg in enumerate(parlay_legs, 1):
        if leg["type"] == "prop":
            print(f"  {i}. {leg['player']} {leg['over_under'].upper()} {leg['line']} {leg['stat']}")
        elif leg["type"] == "spread":
            print(f"  {i}. {leg['team']} {leg['spread']:+.1f}")
        elif leg["type"] == "moneyline":
            print(f"  {i}. {leg['team']} ML")

    # ── Run the simulation ──
    print(f"\nRunning 10,000 simulations...")

    result = price_parlay(
        legs=parlay_legs,
        n_sims=10000,
        seed=42,
        # Chiefs are a good offense, Ravens also strong
        home_rolling_epa=0.10,   # Chiefs recent offensive EPA
        away_rolling_epa=0.15,   # Ravens recent offensive EPA
        home_pass_rate=0.58,     # Chiefs pass rate
        away_pass_rate=0.48,     # Ravens run-heavy scheme
        target_share_draws=target_share_draws,
        target_share_idx=target_share_idx,
        carry_share_draws=carry_share_draws,
        carry_share_idx=carry_share_idx,
        efficiency_lookup=efficiency_lookup,
        position_avgs=position_avgs,
        residual_spreads=residual_spreads,
    )

    print(f"\n── Results ──")
    print(f"Parlay hit rate:  {result['hit_rate']:.4f} ({result['hit_rate']*100:.1f}%)")
    print(f"Hits:             {result['hits']} / {result['total_sims']}")
    print(f"Implied odds:     {result['implied_odds']:+d}" if result['implied_odds'] else "Implied odds: N/A")

    # ── Compare: what if legs were independent? ──
    # Price each leg individually to show the correlation effect
    print("\n── Individual leg prices (for correlation comparison) ──")
    independent_prob = 1.0

    for i, leg in enumerate(parlay_legs, 1):
        single_result = price_parlay(
            legs=[leg],
            n_sims=10000,
            seed=42 + i,
            home_rolling_epa=0.10,
            away_rolling_epa=0.15,
            home_pass_rate=0.58,
            away_pass_rate=0.48,
            target_share_draws=target_share_draws,
            target_share_idx=target_share_idx,
            carry_share_draws=carry_share_draws,
            carry_share_idx=carry_share_idx,
            efficiency_lookup=efficiency_lookup,
            position_avgs=position_avgs,
            residual_spreads=residual_spreads,
        )
        prob = single_result["hit_rate"]
        independent_prob *= prob

        label = ""
        if leg["type"] == "prop":
            label = f"{leg['player']} {leg['over_under'].upper()} {leg['line']}"
        elif leg["type"] == "spread":
            label = f"{leg['team']} {leg['spread']:+.1f}"

        print(f"  Leg {i}: {label} -> {prob:.4f} ({prob*100:.1f}%)")

    print(f"\n  Independent product (no correlation): {independent_prob:.4f} ({independent_prob*100:.1f}%)")
    print(f"  Simulated parlay (with correlation):  {result['hit_rate']:.4f} ({result['hit_rate']*100:.1f}%)")
    print(f"  Difference: {(result['hit_rate'] - independent_prob):.4f}")
    print(f"\n  If the simulated rate > independent product, correlation is")
    print(f"  HELPING this parlay (legs tend to hit together).")
    print(f"  If simulated < independent, correlation is HURTING it.")