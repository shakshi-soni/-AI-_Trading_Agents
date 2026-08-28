"""Schema for the deterministic Risk Engine's output. No LLM involved here."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class RiskCheckResult(BaseModel):
    """Result of a single rule check (e.g. max risk per trade)."""

    rule: str
    passed: bool
    detail: str


class RiskDecision(BaseModel):
    """Aggregate result of running a TradeProposal through all hard risk rules."""

    verdict: RiskVerdict
    checks: list[RiskCheckResult] = Field(default_factory=list)
    reason: str = Field(..., description="Human-readable summary, especially why it failed if it did")
    timestamp: datetime = Field(default_factory=datetime.utcnow)