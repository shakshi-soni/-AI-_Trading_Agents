"""Schema for the Market Agent's output."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MarketDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MarketAnalysis(BaseModel):
    """Structured read on the current market state for a single ticker."""

    ticker: str
    direction: MarketDirection
    confidence: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 confidence in the direction call")
    evidence: list[str] = Field(default_factory=list, description="Short bullet reasons supporting the call")
    current_price: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)