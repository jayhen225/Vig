"""Parlay pricing service.

Prefers the real correlation-aware pricer (parlay/core/layer5_pricer.py). That
needs trained model artifacts under parlay/data/ and heavy deps (arviz/pymc);
when they're absent we fall back to a self-contained correlated simulation that
mirrors the real model's structure (shared per-game factor + independent noise)
so the frontend still demonstrates the correlation edge. Fallback results are
flagged ``source: "estimate"``.

Game-line legs (h2h/spreads/totals) are only supported by the fallback pricer
below, not the real model (parlay/core/layer5_pricer.py only models player-stat
variance, not team scoring) -- a slip containing one always uses the fallback.
The fallback's shared-game-factor mechanism generalizes naturally to team
scoring: the same per-team factor that nudges a QB's passing yards up also
nudges that team's own score, so a spread/total leg genuinely correlates with
that game's player props in the same slip.
"""

import numpy as np

from parlay.core.devig import american_to_prob, prob_to_american

# Rough coefficient of variation per market, used only by the fallback to turn a
# book line into a game-to-game std when the trained variance model isn't loaded.
_FALLBACK_CV = {
    "player_pass_yds": 0.28,
    "player_rush_yds": 0.45,
    "player_reception_yds": 0.50,
}
_GAME_SHARE = 0.40  # matches layer5_pricer: share of variance driven by game script

_GAME_LINE_MARKETS = {"h2h", "spreads", "totals"}

# Rough NFL calibration for the fallback's team-scoring model (points), just
# like _FALLBACK_CV above is a rough calibration for player stats -- this is
# an estimate pricer, not the trained model.
_LEAGUE_AVG_TOTAL = 45.8  # ~2x simulator.py's LEAGUE_AVG_POINTS (22.92)
_TEAM_FACTOR_SENS = 6.5  # points of team-score swing per 1 sd of shared game factor
_MARGIN_NOISE_STD = 9.9  # residual noise so margin std lands near a typical ~13.5 pts
_TOTAL_NOISE_STD = 9.2  # residual noise so total std lands near a typical ~13 pts

# Cache the loaded real models so we only pay the load once per process.
_real_models = None
_real_state = "unloaded"  # unloaded | ready | unavailable


def _load_real_models():
    global _real_models, _real_state
    if _real_state != "unloaded":
        return _real_models
    try:
        from parlay.core import layer5_pricer

        _real_models = {"mod": layer5_pricer, "models": layer5_pricer.load_models()}
        _real_state = "ready"
    except Exception:  # noqa: BLE001 -- missing artifacts/deps -> fall back to estimate pricer
        _real_models = None
        _real_state = "unavailable"
    return _real_models


def price_parlay(legs, n_sims=20000, seed=42):
    """Price a parlay. Returns correlated vs independent probability + edge.

    ``legs``: list of {player, market, line, side ('over'|'under'), team}.
    """
    has_game_line = any(leg["market"] in _GAME_LINE_MARKETS for leg in legs)
    real = None if has_game_line else _load_real_models()
    if real is not None:
        result = _price_with_real_model(real, legs, n_sims, seed)
        if result is not None:
            return result
    return _price_fallback(legs, n_sims, seed)


def _price_with_real_model(real, legs, n_sims, seed):
    mod, models = real["mod"], real["models"]
    variances = {}
    for leg in legs:
        pv = mod.estimate_player_variance(leg["player"], leg["market"], models)
        if pv is None:
            return None
        variances[leg["player"]] = pv
    core_legs = [
        {"player": leg["player"], "market": leg["market"], "book_line": leg["line"],
         "over_under": leg["side"], "team": "home" if leg.get("home", True) else "away"}
        for leg in legs
    ]
    res = mod.price_correlated_parlay(core_legs, variances, n_sims=n_sims, seed=seed)
    if res is None:
        return None
    return _shape(res, legs, source="live")


def _prop_info(leg):
    cv = _FALLBACK_CV.get(leg["market"], 0.4)
    std = max(1e-6, leg["line"] * cv)
    return {
        "kind": "prop", "line": leg["line"], "side": leg["side"], "team": leg.get("team", "?"),
        "game_sens": std * np.sqrt(_GAME_SHARE), "indiv": std * np.sqrt(1 - _GAME_SHARE),
        "std": std,
    }


def _game_line_info(leg):
    home_team, away_team = leg["home_team"], leg["away_team"]
    team = leg.get("team") or home_team
    return {
        "kind": leg["market"], "line": leg["line"], "side": leg["side"],
        "team": team, "game": (home_team, away_team), "is_home": team == home_team,
    }


def _game_state(rng, home_factor, away_factor):
    """One game's simulated margin (home - away) and total, from its two team factors."""
    margin = (home_factor - away_factor) * _TEAM_FACTOR_SENS + rng.normal(0, _MARGIN_NOISE_STD)
    total = _LEAGUE_AVG_TOTAL + (home_factor + away_factor) * _TEAM_FACTOR_SENS + rng.normal(0, _TOTAL_NOISE_STD)
    return {"margin": margin, "total": total}


def _game_line_hits(leg, state):
    team_margin = state["margin"] if leg["is_home"] else -state["margin"]
    if leg["kind"] == "h2h":
        return team_margin > 0
    if leg["kind"] == "spreads":
        return team_margin + leg["line"] > 0
    return _leg_hits(leg, state["total"])  # totals


def _price_fallback(legs, n_sims, seed):
    rng = np.random.default_rng(seed)
    info = [_game_line_info(leg) if leg["market"] in _GAME_LINE_MARKETS else _prop_info(leg)
            for leg in legs]

    prop_teams = {leg["team"] for leg in info if leg["kind"] == "prop"}
    games = {leg["game"] for leg in info if leg["kind"] != "prop"}
    game_teams = {t for pair in games for t in pair}
    teams = prop_teams | game_teams

    hits = 0
    for _ in range(n_sims):
        factors = {t: rng.normal(0, 1) for t in teams}
        game_states = {g: _game_state(rng, factors[g[0]], factors[g[1]]) for g in games}

        ok = True
        for leg in info:
            if leg["kind"] == "prop":
                stat = leg["line"] + factors[leg["team"]] * leg["game_sens"] + rng.normal(0, leg["indiv"])
                hit = _leg_hits(leg, stat)
            else:
                hit = _game_line_hits(leg, game_states[leg["game"]])
            if not hit:
                ok = False
                break
        if ok:
            hits += 1
    correlated = hits / n_sims

    indep_probs = []
    for leg in info:
        if leg["kind"] == "prop":
            h = sum(_leg_hits(leg, leg["line"] + rng.normal(0, leg["std"])) for _ in range(n_sims))
        else:
            h = 0
            for _ in range(n_sims):
                state = _game_state(rng, rng.normal(0, 1), rng.normal(0, 1))
                h += _game_line_hits(leg, state)
        indep_probs.append(h / n_sims)
    independent = float(np.prod(indep_probs))

    res = {"correlated_prob": correlated, "independent_prob": independent,
           "individual_probs": indep_probs, "correlation_edge": correlated - independent}
    return _shape(res, legs, source="estimate")


def _leg_hits(leg, stat):
    return stat > leg["line"] if leg["side"] == "over" else stat < leg["line"]


def _shape(res, legs, source):
    corr = res["correlated_prob"]
    indep = res["independent_prob"]
    return {
        "source": source,
        "correlated_prob": round(corr, 4),
        "independent_prob": round(indep, 4),
        "correlation_edge": round(res["correlation_edge"], 4),
        "fair_price": prob_to_american(corr) if 0 < corr < 1 else None,
        "book_price": prob_to_american(indep) if 0 < indep < 1 else None,
        "individual": [
            {"player": leg.get("player"), "market": leg["market"], "line": leg["line"],
             "side": leg["side"], "team": leg.get("team"), "prob": round(p, 4)}
            for leg, p in zip(legs, res["individual_probs"])
        ],
    }


def implied_prob(price):
    """Expose for callers/tests."""
    return american_to_prob(price)
