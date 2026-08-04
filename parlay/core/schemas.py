from pydantic import BaseModel
from enum import Enum
from typing import Annotated, Union, Literal
from pydantic import Field,  ValidationError
import uuid
class Side(Enum):
    OVER = "over"
    UNDER = "under"

class BetType(Enum):
    SPREAD = "spread"
    MONEYLINE = "moneyline"
    PROP = "prop"

class SpreadLeg(BaseModel):
    team: str
    spread: float
    game_id: str
    bet_type: Literal[BetType.SPREAD]


class MoneylineLeg(BaseModel):
    team: str
    game_id: str
    bet_type: Literal[BetType.MONEYLINE]

class PropLeg(BaseModel):
    player: str
    stat: str
    line: float
    side: Side
    game_id: str
    bet_type: Literal[BetType.PROP]

AnyLeg = Annotated[Union[SpreadLeg, MoneylineLeg, PropLeg], Field(discriminator="bet_type")]

class Parlay(BaseModel):
    legs: list[AnyLeg]
    parlay_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

