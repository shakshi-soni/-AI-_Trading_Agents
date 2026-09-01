"""
Alpaca Service.

Owns the TradingClient connection and any operation that's about the
account/orders/positions themselves — not specific to market data or
options contract selection (those live in their own service files).

Every other file that needs to talk to Alpaca's trading side should
go through this, not instantiate its own TradingClient.
"""

import os
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderStatus, OrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, OptionLegRequest

from app.models.execution import ExecutionResult, ExecutionStatus

TERMINAL_BAD_STATUSES = {
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
    OrderStatus.SUSPENDED,
}


class AlpacaService:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        paper: bool | None = None,
        client: TradingClient | None = None,
    ) -> None:
        """
        Pass an explicit `client` to inject a fake/mock TradingClient for
        testing without hitting the real API. Otherwise a real client is
        built from api_key/secret_key/paper (or the matching env vars).
        """
        if client is not None:
            self.client = client
            return

        api_key = api_key or os.getenv("ALPACA_API_KEY")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if paper is None:
            paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"

        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set. "
                "Set them in .env or pass explicitly."
            )
        if not paper:
            raise ValueError(
                "AlpacaService refuses to initialize against a non-paper "
                "account. Set ALPACA_PAPER=true."
            )

        self.client = TradingClient(api_key, secret_key, paper=True)

    def get_account_summary(self) -> dict:
        """Basic account info used for pre-flight checks and the dashboard."""
        account = self.client.get_account()
        return {
            "status": str(account.status),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "options_trading_level": getattr(account, "options_trading_level", None),
        }

    def account_ready_for_options(self) -> tuple[bool, str]:
        """
        Pre-flight check: is this account active and Level 3+ (required
        for multi-leg spread orders)? Returns (is_ready, reason).
        """
        summary = self.get_account_summary()
        if summary["status"] != "AccountStatus.ACTIVE":
            return False, f"Account not active (status={summary['status']})"

        level = summary["options_trading_level"]
        if level is None:
            return False, "Could not determine options trading level"
        if int(level) < 3:
            return False, f"Options trading level is {level}, need Level 3+ for spreads"

        return True, "Account ready for multi-leg options orders"

    def submit_vertical_spread(
        self,
        long_symbol: str,
        short_symbol: str,
        quantity: int = 1,
    ) -> str:
        """
        Submit a bull-call-style vertical spread as a single MLeg market
        order (buy long_symbol, sell short_symbol). Returns the order id.
        """
        legs = [
            OptionLegRequest(symbol=long_symbol, side="buy", ratio_qty=1),
            OptionLegRequest(symbol=short_symbol, side="sell", ratio_qty=1),
        ]
        order_req = MarketOrderRequest(
            qty=quantity,
            order_class=OrderClass.MLEG,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            legs=legs,
        )
        order = self.client.submit_order(order_req)
        return str(order.id)

    def poll_order_until_filled(
        self,
        order_id: str,
        expected_debit: float | None = None,
        poll_seconds: int = 3,
        max_attempts: int = 20,
    ) -> ExecutionResult:
        """
        Poll an order until it fills or reaches a terminal bad state.
        
        Args:
            order_id: Order ID to poll
            expected_debit: The verified net debit that was expected (for variance tracking)
            poll_seconds: Seconds to wait between poll attempts
            max_attempts: Maximum number of poll attempts
        
        Returns an ExecutionResult regardless of outcome — never raises
        for a normal reject/timeout, only for unexpected API errors.
        """
        last_order = None
        for _ in range(max_attempts):
            last_order = self.client.get_order_by_id(order_id)

            if last_order.status == OrderStatus.FILLED:
                filled_price = (
                    float(last_order.filled_avg_price)
                    if getattr(last_order, "filled_avg_price", None) is not None
                    else None
                )
                
                # Calculate variance if we have both expected debit and actual filled price
                debit_variance = None
                if filled_price is not None and expected_debit is not None:
                    debit_variance = filled_price - expected_debit
                
                return ExecutionResult(
                    status=ExecutionStatus.FILLED,
                    order_id=str(last_order.id),
                    filled_avg_price=filled_price,
                    expected_debit=expected_debit,
                    debit_variance=debit_variance,
                    detail="Order filled.",
                )

            if last_order.status in TERMINAL_BAD_STATUSES:
                return ExecutionResult(
                    status=ExecutionStatus.REJECTED,
                    order_id=str(last_order.id),
                    expected_debit=expected_debit,
                    detail=f"Order reached terminal state: {last_order.status}",
                )

            time.sleep(poll_seconds)

        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            order_id=order_id,
            expected_debit=expected_debit,
            detail=(
                f"Order did not fill within {max_attempts * poll_seconds}s "
                f"(last status: {last_order.status if last_order else 'unknown'})"
            ),
        )

    def get_positions_for_symbols(self, symbols: list[str]) -> list[dict]:
        """Return current positions matching the given option contract symbols."""
        positions = self.client.get_all_positions()
        matches = [p for p in positions if p.symbol in symbols]
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "avg_entry_price": float(p.avg_entry_price),
            }
            for p in matches
        ]