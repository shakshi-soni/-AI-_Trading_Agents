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

        IMPORTANT: this window can span MULTIPLE expiration cycles
        (e.g. several weekly expiries). The returned list is sorted by
        strike only and may contain contracts from different expiration
        dates that happen to share the same strike price. Callers that
        need a genuine vertical spread (both legs same expiry) MUST
        narrow to a single expiration first — see
        select_single_expiration_contracts() below. Do not pick two
        "adjacent" contracts from this raw list directly.
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

    @staticmethod
    def select_single_expiration_contracts(contracts: list[dict]) -> list[dict]:
        """
        Narrow a (possibly multi-expiration) contract list down to just
        the SOONEST available expiration date, so both legs of a spread
        are guaranteed to share the same expiry — this is what makes it
        a genuine vertical spread rather than a diagonal one, and it
        also guarantees each strike price appears at most once (a
        single expiration's chain never lists the same strike twice).
        """
        if not contracts:
            raise NoContractsFoundError("No contracts available to select an expiration from.")

        target_expiration = min(c["expiration_date"] for c in contracts)
        same_expiry = [c for c in contracts if c["expiration_date"] == target_expiration]
        return sorted(same_expiry, key=lambda c: c["strike_price"])

    def select_bull_call_spread_strikes(
        self,
        contracts: list[dict],
        current_price: float,
        spread_width_strikes: int = 2,
    ) -> tuple[dict, dict]:
        """
        Given a sorted list of SAME-EXPIRATION call contracts, pick the
        long leg (nearest strike at/above current price) and the short
        leg (spread_width_strikes higher). Returns (long_contract,
        short_contract) as dicts.

        Callers must pass a single-expiration list (see
        select_single_expiration_contracts) — this method does not
        check expiration itself, only strike ordering.
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

        # Defense in depth: even within a single expiration, guard against
        # any duplicate/non-increasing strike data by advancing short_idx
        # until we find a genuinely higher strike, or fail clearly if none
        # exists. This should be rare (a clean single-expiration chain has
        # unique strikes) but a silent zero-width spread must never reach
        # the caller.
        while (
            short_idx < len(contracts) - 1
            and contracts[short_idx]["strike_price"] <= contracts[long_idx]["strike_price"]
        ):
            short_idx += 1

        if contracts[short_idx]["strike_price"] <= contracts[long_idx]["strike_price"]:
            raise InsufficientStrikesError(
                "Could not find a contract with a strike price genuinely higher "
                f"than the long leg's strike ({contracts[long_idx]['strike_price']}) — "
                "no valid short leg available in this expiration's chain."
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
        End-to-end: find contracts, narrow to a single expiration cycle
        (so both legs genuinely form a vertical spread), pick strikes,
        validate the result, and return a fully described spread ready
        to hand to strategy_agent.py for wrapping into a TradeProposal.
        """
        contracts = self.find_call_contracts(
            underlying_symbol,
            current_price,
            min_days_to_expiry=min_days_to_expiry,
            max_days_to_expiry=max_days_to_expiry,
        )
        same_expiry_contracts = self.select_single_expiration_contracts(contracts)
        long_contract, short_contract = self.select_bull_call_spread_strikes(
            same_expiry_contracts, current_price, spread_width_strikes=spread_width_strikes
        )

        if not self.validate_spread_width(long_contract["strike_price"], short_contract["strike_price"]):
            raise InsufficientStrikesError(
                f"Selected spread failed final validation: long_strike="
                f"{long_contract['strike_price']}, short_strike={short_contract['strike_price']} "
                "— short strike must be strictly greater than long strike."
            )

        if long_contract["expiration_date"] != short_contract["expiration_date"]:
            raise InsufficientStrikesError(
                "Selected spread legs have different expiration dates "
                f"({long_contract['expiration_date']} vs {short_contract['expiration_date']}) "
                "— both legs of a vertical spread must share the same expiry."
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