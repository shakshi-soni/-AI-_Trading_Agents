"""
Adversarial Agent.

Takes a TradeProposal plus the MarketAnalysis it was built from, and
asks the LLM to actively argue against the trade. This is the
signature component of the project: nothing executes without
surviving this challenge.
"""

import json
from typing import Callable

from app.models.adversarial import AdversarialReport, AdversarialVerdict
from app.models.market import MarketAnalysis
from app.models.strategy import TradeProposal

LLMCallable = Callable[[str], str]


class AdversarialAgentError(Exception):
    """Raised when the LLM response can't be parsed into a valid AdversarialReport."""


SYSTEM_INSTRUCTIONS = (
    "You are an adversarial risk-challenge agent. Your job is to evaluate "
    "whether a proposed options trade has merit given current market conditions. "
    "Be critical but fair — reject only if the risk-reward is genuinely poor, "
    "not simply because conditions are uncertain.\n\n"
    "Key criteria:\n"
    "1. MARKET THESIS: Is the bullish/bearish call well-justified? (>0.45 confidence = viable)\n"
    "2. TIME VALUE: With this expiration (14-45 days typical) can the trade profit?\n"
    "3. RISK-REWARD: Max loss vs max profit — spreads are defined-risk (good)\n"
    "4. STRIKE SELECTION: For call spreads, strikes should be near/slightly OTM from current price.\n"
    "   ATM (at-the-money) to 3-5% OTM is normal. Far OTM (10%+) is aggressive/risky.\n"
    "5. TIME TO EXPIRATION: 14-45 days is ideal for options spreads.\n"
    "   Less than 7 days: very short term (theta decay is extreme)\n"
    "   More than 60 days: longer dated (more macro/earnings risk)\n\n"
    "REJECTION RULES:\n"
    "- Reject if: market confidence < 0.35 (bullish call confidence too weak)\n"
    "- Reject if: strikes are >10% OTM from current price AND time-to-expiry <7 days (lottery ticket)\n"
    "- Reject if: days-to-expiry is <3 (too close to expiration, no time value left)\n"
    "- Reject if: risk-reward ratio is worse than 1:0.3 (loss is >3x potential profit)\n"
    "- DO NOT reject just because 'markets could move' — all trades have directional risk\n"
    "- DO NOT reject just because volatility is elevated — high IV actually favors credit spreads\n"
    "- If market thesis is solid (>0.45 conf), strikes are reasonable (ATM-5% OTM), and time is adequate (7-60 days),\n"
    "  the trade should SURVIVE. Be supportive of well-structured spreads.\n\n"
    "Output ONLY a JSON object (no markdown, no extra text):\n"
    '{"verdict": "survive" | "reject", '
    '"thesis_survival": <float 0.0-1.0>, '
    '"weaknesses": [<reasons this could fail>], '
    '"strengths": [<reasons this could succeed>], '
    '"reasoning": <one-sentence summary>}'
)


def build_adversarial_prompt(proposal: TradeProposal, market_analysis: MarketAnalysis) -> str:
    from datetime import date
    days_to_expiry = (proposal.expiration - date.today()).days
    
    # Use VERIFIED economics if available, otherwise fall back to LLM-generated
    max_loss = proposal.verified_max_loss if proposal.verified_max_loss else proposal.max_loss
    max_profit = proposal.verified_max_profit if proposal.verified_max_profit else proposal.max_profit
    spread_width = proposal.verified_spread_width if proposal.verified_spread_width else (proposal.short_strike - proposal.long_strike)
    breakeven = proposal.verified_breakeven if proposal.verified_breakeven else (proposal.long_strike + (max_loss / 100))
    
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"=== VERIFIED FACTS (calculated by Python) ===\n"
        f"Ticker: {proposal.ticker}\n"
        f"Current Price: ${market_analysis.current_price:.2f}\n"
        f"Spread Width: ${spread_width:.2f}\n"
        f"Breakeven Price: ${breakeven:.2f}\n"
        f"Days to Expiration: {days_to_expiry}\n"
        f"Max Loss (per contract): ${max_loss:.2f}\n"
        f"Max Profit (per contract): ${max_profit:.2f}\n"
        f"Quantity: {proposal.quantity}\n"
        f"\n=== TRADE STRUCTURE ===\n"
        f"Strategy: {proposal.strategy.value}\n"
        f"Long strike: ${proposal.long_strike:.2f} (BUY CALL)\n"
        f"Short strike: ${proposal.short_strike:.2f} (SELL CALL)\n"
        f"Expiration: {proposal.expiration}\n"
        f"\n=== MARKET CONTEXT ===\n"
        f"Original market call: {market_analysis.direction.value}, "
        f"confidence={market_analysis.confidence:.2f}\n"
        f"Market evidence cited: {', '.join(market_analysis.evidence) if market_analysis.evidence else 'none'}\n"
        f"Strategy agent's rationale: {proposal.rationale}\n"
    )


class AdversarialAgent:
    def __init__(self, llm_call: LLMCallable) -> None:
        self.llm_call = llm_call

    def attack(self, proposal: TradeProposal, market_analysis: MarketAnalysis) -> AdversarialReport:
        prompt = build_adversarial_prompt(proposal, market_analysis)
        raw_response = self.llm_call(prompt)
        data = self._parse_llm_json(raw_response)

        try:
            verdict = AdversarialVerdict(data["verdict"])
            thesis_survival = float(data["thesis_survival"])
            weaknesses = data.get("weaknesses", [])
            strengths = data.get("strengths", [])
            reasoning = str(data["reasoning"])
            if not isinstance(weaknesses, list):
                weaknesses = [str(weaknesses)]
            if not isinstance(strengths, list):
                strengths = [str(strengths)]
        except (KeyError, ValueError, TypeError) as e:
            raise AdversarialAgentError(
                f"LLM response missing or invalid fields ({e}). Raw response: {raw_response!r}"
            )

        # Build verified facts dict from proposal
        verified_facts = {
            "current_price": market_analysis.current_price,
            "long_strike": proposal.long_strike,
            "short_strike": proposal.short_strike,
            "spread_width": proposal.verified_spread_width or (proposal.short_strike - proposal.long_strike),
            "breakeven_price": proposal.verified_breakeven,
            "max_loss": proposal.verified_max_loss or proposal.max_loss,
            "max_profit": proposal.verified_max_profit or proposal.max_profit,
            "days_to_expiration": (proposal.expiration - __import__('datetime').date.today()).days,
            "expiration": str(proposal.expiration),
        }

        try:
            return AdversarialReport(
                verdict=verdict,
                thesis_survival=thesis_survival,
                verified_facts=verified_facts,
                weaknesses=weaknesses,
                strengths=strengths,
                reasoning=reasoning,
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