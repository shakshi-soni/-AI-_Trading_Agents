"""
Options Service.

Owns everything about finding and validating option contracts and
building a vertical spread from them. strategy_agent.py calls into
this to turn "I want a bullish spread on SPY" into two real,
tradeable Alpaca contract symbols with strikes and an expiration.

No LLM involvement here — this is deterministic contract lookup and
selection logic.
"""

import os
from datetime import date, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus, ContractType, ExerciseStyle
from alpaca.trading.requests import GetOptionContractsRequest


class NoContractsFoundError(Exception):
    """Raised when no contracts match the search criteria."""


class InsufficientStrikesError(Exception):
    """Raised when contracts were found but not enough distinct strikes exist to build a spread."""


class OptionsService:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        client: TradingClient | None = None,
    ) -> None:
        """
        Pass an explicit `client` to inject a fake/mock TradingClient for
        testing without hitting the real API.
        """
        if client is not None:
            self.client = client
            return

        api_key = api_key or os.getenv("ALPACA_API_KEY")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")

        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set. "
                "Set them in .env or pass explicitly."
            )

        self.client = TradingClient(api_key, secret_key, paper=True)

    def find_call_contracts(
        self,
        underlying_symbol: str,
        current_price: float,
        min_days_to_expiry: int = 14,
        max_days_to_expiry: int = 45,
        strike_range_pct_low: float = 0.03,
        strike_range_pct_high: float = 0.05,
    ) -> list[dict]:
        """
        Find active call contracts for the underlying, within an
        expiration window and a strike range around the current price.
        Returns contracts sorted by strike, ascending, as plain dicts.
        """
        today = date.today()
        exp_gte = today + timedelta(days=min_days_to_expiry)
        exp_lte = today + timedelta(days=max_days_to_expiry)

        strike_low = current_price * (1 - strike_range_pct_low)
        strike_high = current_price * (1 + strike_range_pct_high)

        req = GetOptionContractsRequest(
            underlying_symbols=[underlying_symbol],
            status=AssetStatus.ACTIVE,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            strike_price_gte=str(round(strike_low, 2)),
            strike_price_lte=str(round(strike_high, 2)),
            type=ContractType.CALL,
            style=ExerciseStyle.AMERICAN,
        )
        resp = self.client.get_option_contracts(req)
        contracts = resp.option_contracts or []

        if not contracts:
            raise NoContractsFoundError(
                f"No call contracts found for {underlying_symbol} between "
                f"{exp_gte} and {exp_lte}, strikes {strike_low:.2f}-{strike_high:.2f}"
            )

        normalized = [
            {
                "symbol": c.symbol,
                "strike_price": float(c.strike_price),
                "expiration_date": c.expiration_date,
            }
            for c in contracts
        ]
        return sorted(normalized, key=lambda c: c["strike_price"])

    def select_bull_call_spread_strikes(
        self,
        contracts: list[dict],
        current_price: float,
        spread_width_strikes: int = 2,
    ) -> tuple[dict, dict]:
        """
        Given a sorted list of call contracts, pick the long leg (nearest
        strike at/above current price) and the short leg (spread_width_strikes
        higher). Returns (long_contract, short_contract) as dicts.
        """
        if len(contracts) < spread_width_strikes + 1:
            raise InsufficientStrikesError(
                f"Need at least {spread_width_strikes + 1} distinct strikes to "
                f"build a spread of width {spread_width_strikes}, got {len(contracts)}"
            )

        long_idx = next(
            (i for i, c in enumerate(contracts) if c["strike_price"] >= current_price),
            0,
        )
        short_idx = min(long_idx + spread_width_strikes, len(contracts) - 1)

        if short_idx == long_idx:
            raise InsufficientStrikesError(
                "Could not find a distinct higher strike for the short leg "
                "within the available contracts."
            )

        return contracts[long_idx], contracts[short_idx]

    def build_vertical_spread(
        self,
        underlying_symbol: str,
        current_price: float,
        min_days_to_expiry: int = 14,
        max_days_to_expiry: int = 45,
        spread_width_strikes: int = 2,
    ) -> dict:
        """
        End-to-end: find contracts, pick strikes, and return a fully
        described bull call spread ready to hand to strategy_agent.py
        for wrapping into a TradeProposal (max_loss/max_profit still
        need real premium quotes, which strategy_agent computes).
        """
        contracts = self.find_call_contracts(
            underlying_symbol,
            current_price,
            min_days_to_expiry=min_days_to_expiry,
            max_days_to_expiry=max_days_to_expiry,
        )
        long_contract, short_contract = self.select_bull_call_spread_strikes(
            contracts, current_price, spread_width_strikes=spread_width_strikes
        )

        return {
            "underlying": underlying_symbol,
            "long_symbol": long_contract["symbol"],
            "long_strike": long_contract["strike_price"],
            "short_symbol": short_contract["symbol"],
            "short_strike": short_contract["strike_price"],
            "expiration": long_contract["expiration_date"],
        }

    @staticmethod
    def validate_spread_width(long_strike: float, short_strike: float) -> bool:
        """A valid bull call spread requires short_strike > long_strike."""
        return short_strike > long_strike