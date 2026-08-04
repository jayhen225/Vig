from pydantic import BaseModel, model_validator
from enum import Enum
from typing import Annotated, Self, Union, Literal
from pydantic import Field
import parlay
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

def calculate_margin(selected_team, home_team, away_team, home_score, away_score):
    if selected_team not in [home_team, away_team]:
        raise ValueError(f"Selected team {selected_team} is not playing in this game.")
    if selected_team == home_team:
        return home_score - away_score
    elif selected_team == away_team:
        return away_score - home_score


def resolve_spread_leg(leg: SpreadLeg, margin: float):
    if margin is None:
        return ResolutionType.VOIDED
    combine_margin = margin + leg.spread
    if combine_margin > 0:
        return ResolutionType.WIN
    elif combine_margin < 0:
        return ResolutionType.LOSS
    else:
        return ResolutionType.PUSH


def resolve_moneyline_leg(leg: MoneylineLeg, team_score: int, opponent_score: int):
    if team_score is None or opponent_score is None:
        return ResolutionType.VOIDED
    if team_score > opponent_score:
        return ResolutionType.WIN
    elif team_score < opponent_score:
        return ResolutionType.LOSS
    else:
        return ResolutionType.PUSH

def resolve_leg(leg: AnyLeg, **kwargs):
    if isinstance(leg, PropLeg):
        return resolve_prop_leg(leg, **kwargs)
    elif isinstance(leg, SpreadLeg):
        return resolve_spread_leg(leg, **kwargs)
    elif isinstance(leg, MoneylineLeg):
        return resolve_moneyline_leg(leg, **kwargs)
    else:
        raise ValueError(f"Unsupported leg type: {type(leg)}")

class ParlayResolution(BaseModel):
    winning_legs: list[AnyLeg]
    losing_legs: list[AnyLeg]
    voided_legs: list[AnyLeg]
    push_legs: list[AnyLeg]
    result: ResolutionType
    @model_validator(mode='after')
    def parlay_resolver(self) -> Self:
        if len(self.losing_legs) > 0:
            self.result = ResolutionType.LOSS
        elif len(self.winning_legs) > 0:
            self.result = ResolutionType.WIN
        else:
            self.result = ResolutionType.VOIDED
        return self

def resolve_parlay(leg_resolutions: list[tuple[AnyLeg, ResolutionType]]) -> ParlayResolution:
    winning_legs = []
    losing_legs = []
    voided_legs = []
    push_legs = []

    for leg, resolution in leg_resolutions:
        if resolution == ResolutionType.WIN:
            winning_legs.append(leg)
        elif resolution == ResolutionType.LOSS:
            losing_legs.append(leg)
        elif resolution == ResolutionType.VOIDED:
            voided_legs.append(leg)
        elif resolution == ResolutionType.PUSH:
            push_legs.append(leg)

    return ParlayResolution(
        winning_legs=winning_legs,
        losing_legs=losing_legs,
        voided_legs=voided_legs,
        push_legs=push_legs,
        result=ResolutionType.WIN,  # placeholder, validator overwrites this
    )

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

extra_leg = PropLeg(
    player="Derrick Henry",
    stat="rushing_yards",
    line=120.5,
    side=Side.UNDER,
    game_id="game_002",
    bet_type=BetType.PROP,
)

# --- 1. Mixed parlay, all winners ---
# This is the case that would have broken the old **kwargs version —
# a prop, a spread, and a moneyline leg all in one parlay.
result1 = resolve_parlay([
    (prop_leg, ResolutionType.WIN),
    (spread_leg, ResolutionType.WIN),
    (moneyline_leg, ResolutionType.WIN),
])
print(f"Scenario 1 (mixed types, all win): {result1.result}")  # expect WIN

# --- 2. Mixed parlay, one loss ---
result2 = resolve_parlay([
    (prop_leg, ResolutionType.WIN),
    (spread_leg, ResolutionType.LOSS),
    (moneyline_leg, ResolutionType.WIN),
])
print(f"Scenario 2 (mixed types, 1 loss): {result2.result}")  # expect LOSS

# --- 3. Mixed parlay, one void, rest win ---
result3 = resolve_parlay([
    (prop_leg, ResolutionType.WIN),
    (spread_leg, ResolutionType.VOIDED),
    (moneyline_leg, ResolutionType.WIN),
])
print(f"Scenario 3 (mixed types, 1 void, rest win): {result3.result}")  # expect WIN

# --- 4. All voided/pushed, no wins or losses ---
result4 = resolve_parlay([
    (prop_leg, ResolutionType.VOIDED),
    (spread_leg, ResolutionType.PUSH),
])
print(f"Scenario 4 (all void/push): {result4.result}")  # expect VOIDED

# --- 5. Four legs, win + void + loss combined ---
result5 = resolve_parlay([
    (prop_leg, ResolutionType.WIN),
    (spread_leg, ResolutionType.VOIDED),
    (moneyline_leg, ResolutionType.LOSS),
    (extra_leg, ResolutionType.WIN),
])
print(f"Scenario 5 (win, void, loss, win): {result5.result}")  # expect LOSS

# --- 6. Check bucket contents directly, not just overall result ---
print(f"Scenario 5 winning_legs count: {len(result5.winning_legs)}")  # expect 2
print(f"Scenario 5 losing_legs count: {len(result5.losing_legs)}")    # expect 1
print(f"Scenario 5 voided_legs count: {len(result5.voided_legs)}")    # expect 1