"""Trade validation and verified economics calculation.

Deterministically calculates all option economics BEFORE the adversary
sees the trade. This ensures the adversary evaluates based on correct
facts, not LLM-generated guesses.
"""

from dataclasses import dataclass
from datetime import date


OPTIONS_MULTIPLIER = 100  # standard equity options contract multiplier


@dataclass
class VerifiedTradeEconomics:
    """Mathematically verified trade economics — calculated by Python, not LLM."""

    spread_width: float  # short_strike - long_strike (e.g., 10.0)
    net_debit_per_share: float  # actual option premium difference
    net_debit_total: float  # net_debit_per_share × OPTIONS_MULTIPLIER
    max_loss_per_contract: float  # net_debit_total
    max_profit_per_contract: float  # (spread_width - net_debit_per_share) × OPTIONS_MULTIPLIER
    breakeven_price: float  # long_strike + net_debit_per_share
    risk_reward_ratio: float  # max_profit / max_loss
    days_to_expiration: int  # calendar days until option expiration


class TradeValidator:
    """
    Validates and calculates verified trade economics.
    
    This is DETERMINISTIC — no LLM involved. Takes a proposed trade structure
    and calculates mathematically correct economics that the adversary can
    reliably evaluate against.
    """

    @staticmethod
    def validate_and_calculate(
        current_price: float,
        long_strike: float,
        short_strike: float,
        expiration: date,
        estimated_net_debit_pct: float,
        quantity: int = 1,
    ) -> tuple[VerifiedTradeEconomics, list[str]]:
        """
        Validate trade structure and calculate verified economics.
        
        Args:
            current_price: Current stock price
            long_strike: Long call strike (buy)
            short_strike: Short call strike (sell)
            expiration: Option expiration date
            estimated_net_debit_pct: Net debit as fraction of spread width (0.0-1.0)
            quantity: Number of contracts
            
        Returns:
            (VerifiedTradeEconomics, validation_warnings)
        """
        warnings = []

        # --- Sanity checks ---
        if long_strike >= short_strike:
            raise ValueError(
                f"Invalid spread: long_strike ({long_strike}) must be < short_strike ({short_strike})"
            )

        if not (0.0 < estimated_net_debit_pct < 1.0):
            raise ValueError(
                f"estimated_net_debit_pct must be strictly between 0 and 1, got {estimated_net_debit_pct}"
            )

        # --- Calculate verified economics ---
        spread_width = short_strike - long_strike
        net_debit_per_share = estimated_net_debit_pct * spread_width
        net_debit_total = net_debit_per_share * OPTIONS_MULTIPLIER
        max_profit_per_contract = (spread_width - net_debit_per_share) * OPTIONS_MULTIPLIER
        breakeven_price = long_strike + net_debit_per_share

        # Days to expiration
        from datetime import datetime
        days_to_exp = (expiration - date.today()).days

        if days_to_exp < 1:
            raise ValueError(f"Expiration date {expiration} is in the past")

        if days_to_exp < 3:
            warnings.append(f"Very short DTE ({days_to_exp} days) — theta decay will be extreme")

        if days_to_exp > 90:
            warnings.append(f"Long dated ({days_to_exp} days) — macro/earnings risk increases")

        # --- Strike distance checks ---
        long_strike_distance_pct = abs(long_strike - current_price) / current_price
        short_strike_distance_pct = abs(short_strike - current_price) / current_price

        if long_strike_distance_pct > 0.05:
            warnings.append(
                f"Long strike {long_strike} is {long_strike_distance_pct*100:.1f}% away from current price {current_price}"
            )

        if short_strike_distance_pct > 0.10:
            warnings.append(
                f"Short strike {short_strike} is {short_strike_distance_pct*100:.1f}% away — potentially lottery-like"
            )

        # --- Risk/reward check ---
        if max_profit_per_contract <= 0 or net_debit_total <= 0:
            raise ValueError(
                f"Invalid economics: max_profit={max_profit_per_contract}, net_debit={net_debit_total}"
            )

        risk_reward_ratio = max_profit_per_contract / net_debit_total if net_debit_total > 0 else 0

        if risk_reward_ratio < 0.5:
            warnings.append(
                f"Poor risk/reward ratio ({risk_reward_ratio:.2f}) — risking {net_debit_total:.0f} to make {max_profit_per_contract:.0f}"
            )

        # --- Calculate total for quantity ---
        max_loss_total = net_debit_total * quantity
        max_profit_total = max_profit_per_contract * quantity

        economics = VerifiedTradeEconomics(
            spread_width=spread_width,
            net_debit_per_share=net_debit_per_share,
            net_debit_total=net_debit_total,
            max_loss_per_contract=net_debit_total,
            max_profit_per_contract=max_profit_per_contract,
            breakeven_price=breakeven_price,
            risk_reward_ratio=risk_reward_ratio,
            days_to_expiration=days_to_exp,
        )

        return economics, warnings

    @staticmethod
    def calculate_price_target_for_breakeven(
        current_price: float, breakeven_price: float
    ) -> dict:
        """
        Calculate required price move to breakeven.
        
        Returns dict with:
        - required_move: absolute price change
        - required_move_pct: percentage change
        - direction: "up" or "down"
        """
        move = breakeven_price - current_price
        move_pct = (move / current_price) * 100
        direction = "up" if move > 0 else "down"

        return {
            "required_move": abs(move),
            "required_move_pct": abs(move_pct),
            "direction": direction,
        }
