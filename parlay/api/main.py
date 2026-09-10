"""FastAPI backend for the Vig parlay tool.

Endpoints:
  GET  /api/health  -> liveness + whether live models are available
  GET  /api/board   -> this week's +EV props (live from the warehouse, else sample)
  POST /api/price   -> correlation-aware price for a parlay slip

Run (dev):  uvicorn parlay.api.main:app --reload --port 8000
The React dev server proxies /api to this app (see frontend/vite.config.ts).
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from parlay.api import board as board_service
from parlay.api import lines as lines_service
from parlay.api import pricing as pricing_service
from parlay.api.sample_data import (
    GAME_LINE_MARKETS,
    LINE_MARKET_LABELS,
    MARKET_LABELS,
    PRICEABLE_MARKETS,
)

ALL_PRICEABLE_MARKETS = PRICEABLE_MARKETS | GAME_LINE_MARKETS
ALL_MARKET_LABELS = {**MARKET_LABELS, **LINE_MARKET_LABELS}

app = FastAPI(title="Vig API", version="0.1.0")

# Dev: the Vite server (5173) calls the API directly if the proxy is bypassed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Leg(BaseModel):
    # Player-prop legs (player_pass_yds/player_rush_yds/player_reception_yds):
    # player, market, line, side ("over"/"under"), team required.
    #
    # Game-line legs (h2h/spreads/totals): market, home_team, away_team, team
    # (which of the two this leg backs) required; line is null for h2h;
    # side is "over"/"under" for totals, ignored otherwise. player is unused.
    player: str | None = None
    market: str = Field(..., description="e.g. player_pass_yds, h2h, spreads, totals")
    line: float | None = None
    side: str = "over"
    team: str | None = None
    home: bool = True
    home_team: str | None = None
    away_team: str | None = None


class PriceRequest(BaseModel):
    legs: list[Leg] = Field(..., min_length=1, max_length=8)


@app.get("/api/health")
def health():
    pricing_service._load_real_models()
    return {
        "ok": True,
        "models": pricing_service._real_state,  # ready | unavailable
        "priceable_markets": sorted(ALL_PRICEABLE_MARKETS),
    }


@app.get("/api/board")
def board():
    return board_service.get_board()


@app.get("/api/lines")
def lines():
    return lines_service.get_lines()


@app.post("/api/price")
def price(req: PriceRequest):
    unsupported = [leg.market for leg in req.legs if leg.market not in ALL_PRICEABLE_MARKETS]
    if unsupported:
        return {
            "error": "unsupported_market",
            "message": "The pricer only supports pass/rush/reception yards, moneyline, spread, and total.",
            "unsupported": sorted(set(unsupported)),
            "priceable_markets": sorted(ALL_PRICEABLE_MARKETS),
        }
    legs = [leg.model_dump() for leg in req.legs]
    result = pricing_service.price_parlay(legs)
    result["market_labels"] = {m: ALL_MARKET_LABELS[m] for m in {leg["market"] for leg in legs}}
    return result


# Serve the built frontend (frontend/dist) when it exists, so one process can
# host the whole app in production. In dev, use the Vite server instead.
_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
