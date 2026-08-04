from schemas import Side, BetType, SpreadLeg, MoneylineLeg, PropLeg, Parlay
from pydantic import ValidationError

# --- 1. Valid construction of each leg type ---
prop = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)
print("PropLeg created:", prop)

spread = SpreadLeg(
    team="Chiefs",
    spread=-3.5,
    game_id="game_001",
    bet_type=BetType.SPREAD,
)
print("SpreadLeg created:", spread)

moneyline = MoneylineLeg(
    team="Chiefs",
    game_id="game_001",
    bet_type=BetType.MONEYLINE,
)
print("MoneylineLeg created:", moneyline)

# --- 2. The bug: mismatched bet_type currently succeeds when it shouldn't ---
try:
    bad_spread = SpreadLeg(
        team="Chiefs",
        spread=-3.5,
        game_id="game_001",
        bet_type=BetType.PROP,   # <- wrong tag for a SpreadLeg
    )
    print("PROBLEM: SpreadLeg accepted bet_type=PROP without error:", bad_spread)
except ValidationError as e:
    print("Correctly rejected mismatched bet_type:", e)

# --- 3. Invalid data that SHOULD fail regardless ---
try:
    bad_line = PropLeg(
        player="Patrick Mahomes",
        stat="passing_yards",
        line="not_a_number",   # wrong type entirely
        side=Side.OVER,
        game_id="game_001",
        bet_type=BetType.PROP,
    )
    print("PROBLEM: accepted a non-numeric line:", bad_line)
except ValidationError as e:
    print("Correctly rejected bad line type:", e)

prop1 = PropLeg(
    player="Patrick Mahomes",
    stat="passing_yards",
    line=275.5,
    side=Side.OVER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

spread1 = SpreadLeg(
    team="Chiefs",
    spread=-3.5,
    game_id="game_001",
    bet_type=BetType.SPREAD,
)


moneyline1 = MoneylineLeg(
    team="Chiefs",
    game_id="game_001",
    bet_type=BetType.MONEYLINE,
)

prop2 = PropLeg(
    player="Derrick Henry",
    stat="rushing_yards",
    line=120.5,
    side=Side.UNDER,
    game_id="game_001",
    bet_type=BetType.PROP,
)

spread2 = SpreadLeg(
    team="Titans",
    spread=3.5,
    game_id="game_001",
    bet_type=BetType.SPREAD,
)

moneyline2 = MoneylineLeg(
    team="Titans",
    game_id="game_001",
    bet_type=BetType.MONEYLINE,
)

# --- 4. Building a Parlay with mixed leg types ---
try:
    parlay = Parlay(legs=[prop, spread, moneyline])
    print("Parlay created:", parlay)
except Exception as e:
    print("Parlay construction failed:", e)

try:
    parlay1 = Parlay(legs=[prop1, spread1, moneyline1])
    print("Parlay created:", parlay1)
except Exception as e:
    print("Parlay construction failed:", e)

try:
    parlay2 = Parlay(legs=[prop2, spread2, moneyline2])
    print("Parlay created:", parlay2)
except Exception as e:
    print("Parlay construction failed:", e)