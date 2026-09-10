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
from parlay.api.sample_data import MARKET_LABELS, PRICEABLE_MARKETS

app = FastAPI(title="Vig API", version="0.1.0")

# Dev: the Vite server (5173) calls the API directly if the proxy is bypassed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Leg(BaseModel):
    player: str
    market: str = Field(..., description="e.g. player_pass_yds")
    line: float
    side: str = Field("over", pattern="^(over|under)$")
    team: str | None = None
    home: bool = True


class PriceRequest(BaseModel):
    legs: list[Leg] = Field(..., min_length=1, max_length=8)


@app.get("/api/health")
def health():
    pricing_service._load_real_models()
    return {
        "ok": True,
        "models": pricing_service._real_state,  # ready | unavailable
        "priceable_markets": sorted(PRICEABLE_MARKETS),
    }


@app.get("/api/board")
def board():
    return board_service.get_board()


@app.get("/api/lines")
def lines():
    return lines_service.get_lines()


@app.post("/api/price")
def price(req: PriceRequest):
    unsupported = [leg.market for leg in req.legs if leg.market not in PRICEABLE_MARKETS]
    if unsupported:
        return {
            "error": "unsupported_market",
            "message": "The pricer only supports pass/rush/reception yards.",
            "unsupported": sorted(set(unsupported)),
            "priceable_markets": sorted(PRICEABLE_MARKETS),
        }
    legs = [leg.model_dump() for leg in req.legs]
    result = pricing_service.price_parlay(legs)
    result["market_labels"] = {m: MARKET_LABELS[m] for m in {leg["market"] for leg in legs}}
    return result


# Serve the built frontend (frontend/dist) when it exists, so one process can
# host the whole app in production. In dev, use the Vite server instead.
_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
