from datetime import date

from app.agents.adversarial_agent import AdversarialAgent
from app.models.market import MarketAnalysis, MarketDirection
from app.models.strategy import TradeProposal, SpreadType


def test_adversarial_handles_missing_reasoning_field():
    def fake_llm(prompt: str) -> str:
        return '{"verdict":"reject","thesis_survival":0.32,"weaknesses":["Long-term expiration (over 1 year) exposes to significant time decay and macro risk"]}'

    proposal = TradeProposal(
        ticker="AAPL",
        strategy=SpreadType.BULL_CALL_SPREAD,
        expiration=date(2026, 9, 14),
        long_strike=320.0,
        short_strike=330.0,
        long_symbol="AAPL260914C00320000",
        short_symbol="AAPL260914C00330000",
        max_loss=400.0,
        max_profit=600.0,
        quantity=1,
        rationale="valid bullish idea",
        based_on="AAPL bullish conf=0.80",
    )
    market = MarketAnalysis(
        ticker="AAPL",
        direction=MarketDirection.BULLISH,
        confidence=0.80,
        evidence=["test"],
        current_price=319.92,
        timestamp="2026-08-29",
    )

    report = AdversarialAgent(fake_llm).attack(proposal, market)
    assert report.verdict.value == "survive"
    assert report.reasoning
    assert "structurally valid" in report.reasoning.lower() or "pass threshold" in report.reasoning.lower()
