"""
Deterministic Risk Engine.

No LLM involvement anywhere in this file. Every rule here is plain
Python logic checking numbers against configured limits. This is the
hard gate that sits between the adversarial agent's verdict and
actual execution — nothing overrides it.
"""

import os
from datetime import date

from app.models.strategy import TradeProposal
from app.models.risk import RiskDecision, RiskVerdict, RiskCheckResult


class RiskEngine:
    """
    Stateful only in the sense that it tracks how many trades have been
    approved today and cumulative daily loss so far, so it can enforce
    daily limits across multiple calls in the same run.
    """

    def __init__(
        self,
        max_risk_per_trade: float | None = None,
        max_position_size: float | None = None,
        max_daily_trades: int | None = None,
        max_daily_loss: float | None = None,
    ) -> None:
        self.max_risk_per_trade = max_risk_per_trade if max_risk_per_trade is not None else float(
            os.getenv("MAX_RISK_PER_TRADE", 500)
        )
        self.max_position_size = max_position_size if max_position_size is not None else float(
            os.getenv("MAX_POSITION_SIZE", 5000)
        )
        self.max_daily_trades = max_daily_trades if max_daily_trades is not None else int(
            os.getenv("MAX_DAILY_TRADES", 5)
        )
        self.max_daily_loss = max_daily_loss if max_daily_loss is not None else float(
            os.getenv("MAX_DAILY_LOSS", 1000)
        )

        # Running state for the current trading day.
        self._trades_today: int = 0
        self._realized_loss_today: float = 0.0
        self._tracked_date: date = date.today()

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if today != self._tracked_date:
            self._trades_today = 0
            self._realized_loss_today = 0.0
            self._tracked_date = today

    def record_trade_executed(self, realized_pnl: float = 0.0) -> None:
        """Call this after a trade actually executes, to update daily counters."""
        self._reset_if_new_day()
        self._trades_today += 1
        if realized_pnl < 0:
            self._realized_loss_today += abs(realized_pnl)

    def evaluate(self, proposal: TradeProposal) -> RiskDecision:
        """Run every rule against the proposal and return an aggregate decision."""
        self._reset_if_new_day()

        checks: list[RiskCheckResult] = []

        # Rule 1 — max risk per trade
        risk_ok = proposal.max_loss <= self.max_risk_per_trade
        checks.append(
            RiskCheckResult(
                rule="max_risk_per_trade",
                passed=risk_ok,
                detail=(
                    f"max_loss=${proposal.max_loss:.2f} vs limit=${self.max_risk_per_trade:.2f}"
                ),
            )
        )

        # Rule 2 — max position size (notional exposure, using max_loss * quantity as proxy
        # for capital at risk in this spread; conservative since spreads are defined-risk)
        position_size = proposal.max_loss * proposal.quantity
        position_ok = position_size <= self.max_position_size
        checks.append(
            RiskCheckResult(
                rule="max_position_size",
                passed=position_ok,
                detail=(
                    f"position_size=${position_size:.2f} vs limit=${self.max_position_size:.2f}"
                ),
            )
        )

        # Rule 3 — max daily trades
        trades_ok = self._trades_today < self.max_daily_trades
        checks.append(
            RiskCheckResult(
                rule="max_daily_trades",
                passed=trades_ok,
                detail=(
                    f"trades_today={self._trades_today} vs limit={self.max_daily_trades}"
                ),
            )
        )

        # Rule 4 — max daily loss (would this trade's worst case push us over?)
        projected_loss = self._realized_loss_today + proposal.max_loss
        loss_ok = projected_loss <= self.max_daily_loss
        checks.append(
            RiskCheckResult(
                rule="max_daily_loss",
                passed=loss_ok,
                detail=(
                    f"realized_loss_today=${self._realized_loss_today:.2f} + "
                    f"this_trade_max_loss=${proposal.max_loss:.2f} = "
                    f"${projected_loss:.2f} vs limit=${self.max_daily_loss:.2f}"
                ),
            )
        )

        # Rule 5 — sanity check: max_loss must actually be positive and finite
        sane = proposal.max_loss > 0 and proposal.max_profit > 0
        checks.append(
            RiskCheckResult(
                rule="sane_risk_reward",
                passed=sane,
                detail=f"max_loss=${proposal.max_loss:.2f}, max_profit=${proposal.max_profit:.2f}",
            )
        )

        all_passed = all(c.passed for c in checks)
        failed_rules = [c.rule for c in checks if not c.passed]

        if all_passed:
            reason = "All risk checks passed."
        else:
            reason = f"Failed rule(s): {', '.join(failed_rules)}"

        return RiskDecision(
            verdict=RiskVerdict.PASS if all_passed else RiskVerdict.FAIL,
            checks=checks,
            reason=reason,
        )