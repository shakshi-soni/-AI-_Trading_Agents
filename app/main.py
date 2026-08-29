"""
Application entry point.

Wires together real Alpaca services, a real LLM provider, and the
Orchestrator, then runs one pipeline cycle for a given ticker.

Usage:
    python -m app.main --ticker SPY
    python -m app.main --ticker SPY --quantity 2
    python -m app.main --ticker SPY --llm-provider gemini
    python -m app.main --ticker SPY --force-bullish   # DEBUG ONLY, see below

If --ticker is omitted, the first symbol in the WATCHLIST env var is
used.

--force-bullish is a DEBUG-ONLY flag. It bypasses the real market
agent's LLM call and injects a canned bullish result instead, so you
can verify that strategy/adversarial/risk/execution all work end to
end without waiting for the market to actually read bullish. The
strategy and adversarial agents still make REAL LLM calls, and
execution still hits REAL Alpaca — only the market read is faked.
Never use this flag for your actual hackathon demo/submission run.
"""

import argparse
import json
import os
import sys
from typing import Callable

from dotenv import load_dotenv

from app.agents.adversarial_agent import AdversarialAgent
from app.agents.market_agent import MarketAgent
from app.agents.strategy_agent import StrategyAgent
from app.audit.audit_logger import AuditLogger
from app.orchestrator import Orchestrator
from app.risk.risk_engine import RiskEngine
from app.services.alpaca_service import AlpacaService
from app.services.market_data_service import MarketDataService
from app.services.options_service import OptionsService

SUPPORTED_LLM_PROVIDERS = ("groq", "gemini")


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def get_llm_call(provider: str):
    """
    Build a plain callable(prompt: str) -> str backed by the chosen LLM
    provider. Keeps the SDK-specific code isolated to this one function
    so agents never import Groq/Gemini directly.
    """
    provider = provider.lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise ConfigError(
            f"Unsupported LLM provider '{provider}'. Supported: {SUPPORTED_LLM_PROVIDERS}"
        )

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        if not api_key:
            raise ConfigError("GROQ_API_KEY not set in environment.")

        from groq import Groq

        client = Groq(api_key=api_key)

        def call(prompt: str) -> str:
            # openai/gpt-oss-20b and openai/gpt-oss-120b are reasoning models:
            # they think internally (in a separate `reasoning` field) before
            # writing the final answer to `content`. With a low token budget,
            # reasoning can consume the whole budget and leave `content`
            # empty. reasoning_effort="low" keeps thinking short, and a
            # generous max_completion_tokens ensures room for both the
            # reasoning and the actual JSON answer.
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_completion_tokens=1024,
                reasoning_effort="low",
            )
            content = response.choices[0].message.content
            return content if content else ""

        return call

    # provider == "gemini"
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    if not api_key:
        raise ConfigError("GEMINI_API_KEY not set in environment.")

    from google import genai

    client = genai.Client(api_key=api_key)

    def call(prompt: str) -> str:
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text

    return call


def get_market_agent_llm_call(base_llm_call: Callable[[str], str], force_bullish: bool) -> Callable[[str], str]:
    """
    DEBUG HELPER. Returns base_llm_call unchanged unless force_bullish is
    True, in which case it returns a canned bullish JSON response instead
    of calling the real LLM — used only to unblock testing of downstream
    pipeline stages without waiting for real market conditions.
    """
    if not force_bullish:
        return base_llm_call

    def forced_bullish_call(prompt: str) -> str:
        return json.dumps({
            "direction": "bullish",
            "confidence": 0.80,
            "evidence": ["DEBUG: --force-bullish flag used to test downstream pipeline stages"],
        })

    return forced_bullish_call


def get_default_ticker() -> str:
    watchlist = os.getenv("WATCHLIST", "")
    symbols = [s.strip() for s in watchlist.split(",") if s.strip()]
    if not symbols:
        raise ConfigError(
            "No --ticker provided and WATCHLIST env var is empty. "
            "Set WATCHLIST=SPY,QQQ,... in .env or pass --ticker explicitly."
        )
    return symbols[0]


def build_orchestrator(llm_provider: str, force_bullish: bool = False) -> Orchestrator:
    """Construct a fully wired Orchestrator using real Alpaca + LLM services."""
    llm_call = get_llm_call(llm_provider)
    market_llm_call = get_market_agent_llm_call(llm_call, force_bullish)

    market_data_service = MarketDataService()
    options_service = OptionsService()
    alpaca_service = AlpacaService()

    market_agent = MarketAgent(market_data_service=market_data_service, llm_call=market_llm_call)
    strategy_agent = StrategyAgent(options_service=options_service, llm_call=llm_call)
    adversarial_agent = AdversarialAgent(llm_call=llm_call)

    risk_engine = RiskEngine()
    audit_logger = AuditLogger()

    return Orchestrator(
        market_agent=market_agent,
        strategy_agent=strategy_agent,
        adversarial_agent=adversarial_agent,
        risk_engine=risk_engine,
        alpaca_service=alpaca_service,
        audit_logger=audit_logger,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one adversarial options trading pipeline cycle.")
    parser.add_argument("--ticker", type=str, default=None, help="Ticker to analyze (default: first symbol in WATCHLIST)")
    parser.add_argument("--quantity", type=int, default=1, help="Number of spreads to trade if approved (default: 1)")
    parser.add_argument(
        "--llm-provider",
        type=str,
        default=os.getenv("LLM_PROVIDER", "groq"),
        choices=SUPPORTED_LLM_PROVIDERS,
        help="Which LLM provider to use for all three agents (default: groq, or LLM_PROVIDER env var)",
    )
    parser.add_argument(
        "--force-bullish",
        action="store_true",
        help=(
            "DEBUG ONLY: bypass the real market read and force a bullish "
            "signal, so you can test strategy/adversarial/risk/execution "
            "end to end without waiting for real bullish conditions. "
            "Never use this for your actual demo/submission run."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)

    try:
        ticker = args.ticker or get_default_ticker()
        orchestrator = build_orchestrator(args.llm_provider, force_bullish=args.force_bullish)
    except ConfigError as e:
        print(f"🛑 Configuration error: {e}", file=sys.stderr)
        return 1

    if args.force_bullish:
        print("⚠️  DEBUG MODE: --force-bullish is active. Market read is FAKE. Do not use this for your real demo.")

    print(f"Running pipeline for {ticker} (quantity={args.quantity}, llm={args.llm_provider})...")

    try:
        result = orchestrator.run(ticker, quantity=args.quantity)
    except Exception as e:
        print(f"🛑 Pipeline run failed with an unexpected error: {e}", file=sys.stderr)
        return 1

    print(f"\nrun_id: {result.run_id}")
    print(f"stage reached: {result.stage_reached}")
    print(f"executed: {result.executed}")
    print(f"summary: {result.summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main())