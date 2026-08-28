"""Schema for the Strategy Agent's output — a proposed vertical spread."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class SpreadType(str, Enum):
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"


class TradeProposal(BaseModel):
    """A single proposed vertical spread, not yet challenged or risk-checked."""

    ticker: str
    strategy: SpreadType
    expiration: date
    long_strike: float
    short_strike: float
    long_symbol: str = Field(..., description="OCC contract symbol for the long leg")
    short_symbol: str = Field(..., description="OCC contract symbol for the short leg")
    max_loss: float = Field(..., gt=0, description="Worst-case $ loss on this spread")
    max_profit: float = Field(..., gt=0, description="Best-case $ profit on this spread")
    quantity: int = Field(default=1, gt=0)
    rationale: str = Field(..., description="Why the strategy agent picked this trade")
    based_on: str = Field(..., description="Ticker/direction from the MarketAnalysis this was derived from")
    timestamp: datetime = Field(default_factory=datetime.utcnow)