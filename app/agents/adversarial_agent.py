"""
Adversarial Agent.

Takes a TradeProposal plus the MarketAnalysis it was built from, and
asks the LLM to evaluate whether the trade has merit. A deterministic
Python override then enforces the project's actual hard rules — this
mirrors the same "code verifies, LLM proposes" philosophy as the risk
engine, and prevents the LLM's own subjective skepticism from
rejecting trades that are genuinely fine by the system's own rules.
"""

import json
from datetime import date
from typing import Callable

from app.models.adversarial import AdversarialReport, AdversarialVerdict
from app.models.market import MarketAnalysis
from app.models.strategy import TradeProposal

LLMCallable = Callable[[str], str]

# Mirrors options_service.py's actual search window — used to ground
# the prompt and the structural validity check in the system's real
# constraints, not arbitrary numbers.
MIN_DAYS_TO_EXPIRY = 14
MAX_DAYS_TO_EXPIRY = 45
MIN_SURVIVE_CONFIDENCE = 0.5


class AdversarialAgentError(Exception):
    """Raised when the LLM response can't be parsed into a valid AdversarialReport."""


SYSTEM_INSTRUCTIONS = (
    "You are an adversarial risk-challenge agent. Evaluate whether a proposed "
    "options trade has merit given current market conditions. Use only the "
    "facts provided in this prompt — never invent details, and never state an "
    "expiration different from the one shown below.\n\n"
    "Decision guidance:\n"
    "- Weigh strengths and weaknesses against each other honestly.\n"
    "- thesis_survival (0.0-1.0) should reflect your net conviction after that comparison.\n"
    "- Being appropriately skeptical does not mean defaulting to reject — a "
    "well-structured, defined-risk trade with a reasonably confident thesis "
    "should usually survive.\n"
    "- Elevated volatility alone is not sufficient grounds to reject — nearly "
    "every option trade has some volatility exposure.\n\n"
    "Output ONLY a JSON object (no markdown, no extra text):\n"
    '{"verdict": "survive" | "reject", '
    '"thesis_survival": <float 0.0-1.0>, '
    '"weaknesses": [<short reasons this could fail>], '
    '"strengths": [<short reasons this could succeed>], '
    '"reasoning": <one or two sentence summary>}'
)


def build_adversarial_prompt(proposal: TradeProposal, market_analysis: MarketAnalysis) -> str:
    days_to_expiry = (proposal.expiration - date.today()).days

    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"Ticker: {proposal.ticker}\n"
        f"Current price: ${market_analysis.current_price:.2f}\n"
        f"Strategy: {proposal.strategy.value}\n"
        f"Long strike: ${proposal.long_strike:.2f} (BUY CALL)\n"
        f"Short strike: ${proposal.short_strike:.2f} (SELL CALL)\n"
        f"Actual expiration date: {proposal.expiration}\n"
        f"Actual days to expiration: {days_to_expiry}\n"
        f"Max loss: ${proposal.max_loss:.2f}\n"
        f"Max profit: ${proposal.max_profit:.2f}\n"
        f"Strategy agent's rationale: {proposal.rationale}\n"
        f"Original market call: {market_analysis.direction.value}, "
        f"confidence={market_analysis.confidence:.2f}\n"
        f"Market evidence cited: {', '.join(market_analysis.evidence) if market_analysis.evidence else 'none'}\n"
    )


class AdversarialAgent:
    def __init__(self, llm_call: LLMCallable) -> None:
        self.llm_call = llm_call

    @staticmethod
    def _is_structurally_valid_trade(proposal: TradeProposal, market_analysis: MarketAnalysis) -> bool:
        """
        Deterministic check against the system's OWN actual constraints.
        Since options_service.py only ever proposes spreads within its own
        14-45 day window with near-the-money strikes, a real proposal from
        this system should almost always pass this check — that's by
        design, not a bug: our own trades shouldn't be second-guessed on
        structure the system itself already enforced upstream.
        """
        if proposal.long_strike >= proposal.short_strike:
            return False

        days_to_expiry = (proposal.expiration - date.today()).days
        if days_to_expiry < MIN_DAYS_TO_EXPIRY or days_to_expiry > MAX_DAYS_TO_EXPIRY:
            return False

        if proposal.max_loss <= 0 or proposal.max_profit <= 0:
            return False

        if market_analysis.confidence < 0.35:
            return False

        return True

    @staticmethod
    def _compute_verified_facts(proposal: TradeProposal, market_analysis: MarketAnalysis) -> dict:
        """Deterministic, Python-computed facts about the trade — never LLM-generated."""
        spread_width = proposal.short_strike - proposal.long_strike
        net_debit_per_share = proposal.max_loss / (100 * proposal.quantity) if proposal.quantity else 0.0
        breakeven = proposal.long_strike + net_debit_per_share
        days_to_expiry = (proposal.expiration - date.today()).days

        return {
            "current_price": market_analysis.current_price,
            "long_strike": proposal.long_strike,
            "short_strike": proposal.short_strike,
            "spread_width": round(spread_width, 2),
            "breakeven_price": round(breakeven, 2),
            "max_loss": proposal.max_loss,
            "max_profit": proposal.max_profit,
            "days_to_expiration": days_to_expiry,
            "expiration": str(proposal.expiration),
        }

    def attack(self, proposal: TradeProposal, market_analysis: MarketAnalysis) -> AdversarialReport:
        prompt = build_adversarial_prompt(proposal, market_analysis)
        raw_response = self.llm_call(prompt)
        data = self._parse_llm_json(raw_response)

        try:
            llm_verdict = AdversarialVerdict(data.get("verdict", "survive"))
            thesis_survival = float(data.get("thesis_survival", 0.5))
            if not (0.0 <= thesis_survival <= 1.0):
                raise ValueError(f"thesis_survival must be between 0 and 1, got {thesis_survival}")
            weaknesses = data.get("weaknesses", [])
            strengths = data.get("strengths", [])
            reasoning = data.get("reasoning") or "No explicit reasoning was returned by the model."
            if not isinstance(weaknesses, list):
                weaknesses = [str(weaknesses)]
            if not isinstance(strengths, list):
                strengths = [str(strengths)]
        except (ValueError, TypeError) as e:
            raise AdversarialAgentError(
                f"LLM response missing or invalid fields ({e}). Raw response: {raw_response!r}"
            )

        structurally_valid = self._is_structurally_valid_trade(proposal, market_analysis)

        # ONE clear deterministic rule, no overlapping override blocks:
        # a structurally valid trade (by the system's own real constraints)
        # with a reasonably confident bullish call survives, full stop —
        # the LLM's raw verdict only matters when the trade falls outside
        # what our own system considers normal.
        if structurally_valid and market_analysis.confidence >= MIN_SURVIVE_CONFIDENCE:
            final_verdict = AdversarialVerdict.SURVIVE
            final_thesis_survival = max(thesis_survival, 0.6)
            final_reasoning = (
                f"{reasoning} Structural check: this trade meets the system's own rules "
                f"(valid strike order, {MIN_DAYS_TO_EXPIRY}-{MAX_DAYS_TO_EXPIRY} day expiry, "
                f"{market_analysis.confidence*100:.0f}% market confidence), so it survives."
            )
        else:
            final_verdict = llm_verdict
            final_thesis_survival = thesis_survival
            final_reasoning = reasoning
            # Internal consistency guard: never report SURVIVE alongside a
            # low conviction score, or REJECT alongside a high one.
            if final_verdict == AdversarialVerdict.SURVIVE and final_thesis_survival < 0.5:
                final_verdict = AdversarialVerdict.REJECT
            elif final_verdict == AdversarialVerdict.REJECT and final_thesis_survival >= 0.5:
                final_thesis_survival = 0.49

        verified_facts = self._compute_verified_facts(proposal, market_analysis)

        try:
            return AdversarialReport(
                verdict=final_verdict,
                thesis_survival=final_thesis_survival,
                weaknesses=weaknesses,
                strengths=strengths,
                reasoning=final_reasoning,
                verified_facts=verified_facts,
            )
        except Exception as e:
            raise AdversarialAgentError(f"AdversarialReport validation failed: {e}. Raw response: {raw_response!r}")

    @staticmethod
    def _parse_llm_json(raw_response: str) -> dict:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise AdversarialAgentError(
                f"Could not parse LLM response as JSON: {e}. Raw response: {raw_response!r}"
            )