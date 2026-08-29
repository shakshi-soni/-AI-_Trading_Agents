"""Schema for the Adversarial Agent's output — its attempt to kill the trade."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AdversarialVerdict(str, Enum):
    SURVIVE = "survive"
    REJECT = "reject"


class AdversarialReport(BaseModel):
    """Result of the adversarial agent attacking a TradeProposal."""

    verdict: AdversarialVerdict
    thesis_survival: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 — how well the trade held up")
    
    # Verified facts (calculated by Python, not LLM)
    verified_facts: dict = Field(
        default_factory=dict,
        description="Mathematically verified trade economics (spread width, max loss/profit, breakeven, etc.)"
    )
    
    # Adversarial arguments based on facts
    weaknesses: list[str] = Field(default_factory=list, description="Reasons the trade might fail")
    strengths: list[str] = Field(default_factory=list, description="Reasons the trade might still hold")
    reasoning: str = Field(..., description="Short summary of the adversarial agent's overall judgment")
    timestamp: datetime = Field(default_factory=datetime.utcnow)