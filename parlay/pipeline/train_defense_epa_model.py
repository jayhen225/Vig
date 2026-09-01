import numpy as np

LEAGUE_AVG_DEF_EPA = 0.0024
DEF_EPA_SPREAD = 0.2170

def draw_defense_epa(spread=DEF_EPA_SPREAD, rng=None):
    if rng is None:
        rng = np.random.default_rng()
    return rng.normal(loc=LEAGUE_AVG_DEF_EPA, scale=spread)