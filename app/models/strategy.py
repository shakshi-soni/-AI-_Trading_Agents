"""Schema for the Strategy Agent's output — a proposed vertical spread."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

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
    
    # LLM-generated economics (to be validated and replaced by TradeValidator)
    max_loss: float = Field(..., gt=0, description="Worst-case $ loss on this spread")
    max_profit: float = Field(..., gt=0, description="Best-case $ profit on this spread")
    
    # Verified economics (populated by TradeValidator after strategy proposal)
    verified_max_loss: Optional[float] = Field(
        default=None,
        description="Verified max loss (calculated by Python, not LLM)"
    )
    verified_max_profit: Optional[float] = Field(
        default=None,
        description="Verified max profit (calculated by Python, not LLM)"
    )
    verified_spread_width: Optional[float] = Field(default=None)
    verified_net_debit: Optional[float] = Field(default=None)
    verified_breakeven: Optional[float] = Field(default=None)
    verification_warnings: list[str] = Field(default_factory=list)
    
    quantity: int = Field(default=1, gt=0)
    rationale: str = Field(..., description="Why the strategy agent picked this trade")
    based_on: str = Field(..., description="Ticker/direction from the MarketAnalysis this was derived from")
    timestamp: datetime = Field(default_factory=datetime.utcnow)