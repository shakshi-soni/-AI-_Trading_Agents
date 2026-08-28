"""Schema for the final execution outcome after an approved trade hits Alpaca."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"  # used when risk/adversarial rejected before execution


class ExecutionResult(BaseModel):
    """What actually happened when (or if) the trade reached Alpaca."""

    status: ExecutionStatus
    order_id: str | None = None
    filled_avg_price: float | None = None
    detail: str = Field(default="", description="Error message or extra context if not filled")
    timestamp: datetime = Field(default_factory=datetime.utcnow)