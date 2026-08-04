from pydantic import BaseModel
from enum import Enum
from typing import Annotated, Union, Literal
from pydantic import Field
from parlay.core.resolution import calculate_margin, resolve_leg
from parlay.core.schemas import AnyLeg, Side, SpreadLeg, MoneylineLeg, PropLeg, BetType

class ResolutionType(Enum): 
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    VOIDED = "voided"


def resolve_prop_leg(leg: PropLeg, actual_stat: float):
    if actual_stat is None:
        return ResolutionType.VOIDED
    if leg.side == Side.OVER:
        if actual_stat > leg.line:
            return ResolutionType.WIN
        elif actual_stat < leg.line:
            return ResolutionType.LOSS
        else:
            return ResolutionType.PUSH
    else: 
        if actual_stat < leg.line:
            return ResolutionType.WIN
        elif actual_stat > leg.line:
            return ResolutionType.LOSS
        else:
            return ResolutionType.PUSH
prop_voided = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)
prop_under = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=277.5,
    side=Side.UNDER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

prop_push = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

prop_over_win = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

prop_under_loss = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.UNDER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

try:
    result = resolve_leg(prop_over_win, actual_stat=300)
    print(f"Prop leg resolution: {result}")  # expect WIN
except Exception as e:
    print(f"Error resolving prop leg: {e}")

try:
    result = resolve_leg(prop_under_loss, actual_stat=300)
    print(f"Prop leg resolution: {result}")  # expect LOSS
except Exception as e:
    print(f"Error resolving prop leg: {e}")
try: 
    result = resolve_leg(prop_voided, actual_stat= None)
    print(f"Prop leg resolution: {result}")
except Exception as e:
    print(f"Error resolving prop leg: {e}")

try: 
    result = resolve_leg(prop_under, actual_stat= 260)
    print(f"Prop leg resolution: {result}")
except Exception as e:
    print(f"Error resolving prop leg: {e}")

try:
    result = resolve_leg(prop_push, actual_stat= 275.5)
    print(f"Prop leg resolution: {result}")
except Exception as e:
    print(f"Error resolving prop leg: {e}")

try:
    result = calculate_margin("Team A", "Team A", "Team B", 24, 17)
    print(f"Margin for Team A: {result}")  # expect 7
except Exception as e:
    print(f"Error calculating margin: {e}")

try:
    result = calculate_margin("Team B", "Team A", "Team B", 24, 17)
    print(f"Margin for Team B: {result}")  # expect -7
except Exception as e:
    print(f"Error calculating margin: {e}")

prop_leg = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

spread_leg = SpreadLeg(
    team="Chiefs",
    spread=-3.5,
    game_id="game_001",
    bet_type=BetType.SPREAD,
)

moneyline_leg = MoneylineLeg(
    team="Chiefs",
    game_id="game_001",
    bet_type=BetType.MONEYLINE,
)

# --- Prop leg via router ---
try:
    result = resolve_leg(prop_leg, actual_stat=300)
    print(f"Prop via resolve_leg: {result}")  # expect WIN
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(prop_leg, actual_stat=None)
    print(f"Prop via resolve_leg (voided): {result}")  # expect VOIDED
except Exception as e:
    print(f"Error: {e}")

# --- Spread leg via router ---
try:
    result = resolve_leg(spread_leg, margin=4.0)
    print(f"Spread via resolve_leg: {result}")  # expect WIN (4 + -3.5 = 0.5)
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(spread_leg, margin=2.0)
    print(f"Spread via resolve_leg: {result}")  # expect LOSS (2 + -3.5 = -1.5)
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(spread_leg, margin=None)
    print(f"Spread via resolve_leg (voided): {result}")  # expect VOIDED
except Exception as e:
    print(f"Error: {e}")

# --- Moneyline leg via router ---
try:
    result = resolve_leg(moneyline_leg, team_score=27, opponent_score=24)
    print(f"Moneyline via resolve_leg: {result}")  # expect WIN
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(moneyline_leg, team_score=17, opponent_score=27)
    print(f"Moneyline via resolve_leg: {result}")  # expect LOSS
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(moneyline_leg, team_score=24, opponent_score=24)
    print(f"Moneyline via resolve_leg: {result}")  # expect PUSH
except Exception as e:
    print(f"Error: {e}")

try:
    result = resolve_leg(moneyline_leg, team_score=None, opponent_score=27)
    print(f"Moneyline via resolve_leg (voided): {result}")  # expect VOIDED
except Exception as e:
    print(f"Error: {e}")

# --- Deliberately mismatched kwargs, to see the error shape ---
try:
    result = resolve_leg(prop_leg, margin=3.5)
    print(f"Mismatched kwargs result: {result}")
except Exception as e:
    print(f"Mismatched kwargs correctly raised: {e}")

# --- Unsupported leg type ---
class FakeLeg:
    pass

try:
    result = resolve_leg(FakeLeg())
    print(f"Unsupported leg result: {result}")
except Exception as e:
    print(f"Unsupported leg correctly raised: {e}")