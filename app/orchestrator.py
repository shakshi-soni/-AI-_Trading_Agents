"""
Orchestrator.

Controls the sequence: Market Agent -> Strategy Agent -> Trade Validator ->
Adversarial Agent -> Risk Engine -> Execution -> Audit. Contains no trading
logic itself — every decision is made by the component responsible for it.
This file only sequences calls and decides whether to continue or
stop based on each component's verdict.
"""

import json
import logging
from dataclasses import dataclass

from app.agents.adversarial_agent import AdversarialAgent
from app.agents.market_agent import MarketAgent
from app.agents.strategy_agent import StrategyAgent, StrategyAgentError
from app.audit.audit_logger import AuditLogger
from app.models.adversarial import AdversarialVerdict
from app.models.execution import ExecutionResult, ExecutionStatus
from app.models.risk import RiskVerdict
from app.models.trade_validation import TradeValidator
from app.risk.risk_engine import RiskEngine
from app.services.alpaca_service import AlpacaService

# Setup logging for pipeline tracing
logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """What the orchestrator returns after one full run."""

    run_id: str
    stage_reached: str  # "market" | "strategy" | "adversarial" | "risk" | "execution"
    executed: bool
    summary: str


class Orchestrator:
    def __init__(
        self,
        market_agent: MarketAgent,
        strategy_agent: StrategyAgent,
        adversarial_agent: AdversarialAgent,
        risk_engine: RiskEngine,
        alpaca_service: AlpacaService,
        audit_logger: AuditLogger,
    ) -> None:
        self.market_agent = market_agent
        self.strategy_agent = strategy_agent
        self.adversarial_agent = adversarial_agent
        self.risk_engine = risk_engine
        self.alpaca_service = alpaca_service
        self.audit_logger = audit_logger

    def run(self, ticker: str, quantity: int = 1) -> PipelineResult:
        market_analysis = None
        trade_proposal = None
        adversarial_report = None
        risk_decision = None
        execution_result = None

        logger.info(f"=== PIPELINE START: {ticker} (quantity={quantity}) ===")

        # --- Stage 1: Market Agent ---
        logger.info(f"[1/5] Running Market Agent for {ticker}...")
        market_analysis = self.market_agent.analyze(ticker)
        logger.info(
            f"[1/5] Market analysis complete: direction={market_analysis.direction.value}, "
            f"confidence={market_analysis.confidence:.2f}, price=${market_analysis.current_price:.2f}"
        )

        # --- Stage 2: Strategy Agent ---
        # A non-bullish call is one reason this can stop here, but it is
        # NOT the only reason — a malformed/invalid LLM response for the
        # strategy step also raises StrategyAgentError. We always persist
        # the real exception text as stop_reason so the UI never has to
        # guess why no trade was proposed.
        logger.info(f"[2/5] Running Strategy Agent...")
        try:
            trade_proposal = self.strategy_agent.propose(market_analysis, quantity=quantity)
            logger.info(
                f"[2/5] Strategy complete: {trade_proposal.strategy.value}, "
                f"strikes ${trade_proposal.long_strike}-${trade_proposal.short_strike}, "
                f"max_loss=${trade_proposal.max_loss:.2f}, max_profit=${trade_proposal.max_profit:.2f}"
            )
        except StrategyAgentError as e:
            summary = f"No trade proposed: {e}"
            logger.info(f"[2/5] Strategy Agent stopped: {e}")
            run_id = self.audit_logger.log_run(market_analysis=market_analysis, stop_reason=summary)
            return PipelineResult(
                run_id=run_id,
                stage_reached="market",
                executed=False,
                summary=summary,
            )

        # --- Stage 2.5: Deterministic Trade Validator ---
        # Validates economics and calculates verified max_loss/max_profit BEFORE adversary sees it
        logger.info(f"[2.5/5] Running Trade Validator (deterministic)...")
        try:
            validator = TradeValidator()
            economics, warnings = validator.validate_and_calculate(
                current_price=market_analysis.current_price,
                long_strike=trade_proposal.long_strike,
                short_strike=trade_proposal.short_strike,
                expiration=trade_proposal.expiration,
                estimated_net_debit_pct=(trade_proposal.max_loss / 100) / (trade_proposal.short_strike - trade_proposal.long_strike),
                quantity=quantity,
            )
            
            # Update trade proposal with VERIFIED economics
            trade_proposal.verified_spread_width = economics.spread_width
            trade_proposal.verified_net_debit = economics.net_debit_total
            trade_proposal.verified_max_loss = economics.max_loss_per_contract * quantity
            trade_proposal.verified_max_profit = economics.max_profit_per_contract * quantity
            trade_proposal.verified_breakeven = economics.breakeven_price
            trade_proposal.verification_warnings = warnings
            
            logger.info(
                f"[2.5/5] Trade validation complete: verified_max_loss=${trade_proposal.verified_max_loss:.2f}, "
                f"verified_max_profit=${trade_proposal.verified_max_profit:.2f}, breakeven=${economics.breakeven_price:.2f}"
            )
            if warnings:
                logger.info(f"[2.5/5] Validation warnings: {', '.join(warnings)}")
        except ValueError as e:
            summary = f"Trade validation failed: {e}"
            logger.error(f"[2.5/5] Validation error: {e}")
            run_id = self.audit_logger.log_run(
                market_analysis=market_analysis,
                trade_proposal=trade_proposal,
                stop_reason=summary,
            )
            return PipelineResult(
                run_id=run_id,
                stage_reached="strategy",
                executed=False,
                summary=summary,
            )
        logger.info(f"[3/5] Running Adversarial Agent...")
        adversarial_report = self.adversarial_agent.attack(trade_proposal, market_analysis)
        logger.info(
            f"[3/5] Adversarial complete: verdict={adversarial_report.verdict.value}, "
            f"thesis_survival={adversarial_report.thesis_survival:.2f}"
        )

        if adversarial_report.verdict == AdversarialVerdict.REJECT:
            summary = f"Trade rejected by adversarial agent: {adversarial_report.reasoning}"
            logger.info(f"[3/5] TRADE REJECTED: {summary}")
            run_id = self.audit_logger.log_run(
                market_analysis=market_analysis,
                trade_proposal=trade_proposal,
                adversarial_report=adversarial_report,
                stop_reason=summary,
            )
            return PipelineResult(
                run_id=run_id,
                stage_reached="adversarial",
                executed=False,
                summary=summary,
            )
        
        logger.info(f"[3/5] Trade SURVIVED adversarial challenge")

        # --- Stage 4: Risk Engine ---
        logger.info(f"[4/5] Running Risk Engine...")
        risk_decision = self.risk_engine.evaluate(trade_proposal)
        logger.info(
            f"[4/5] Risk decision: verdict={risk_decision.verdict.value}, reason={risk_decision.reason}"
        )

        if risk_decision.verdict == RiskVerdict.FAIL:
            summary = f"Trade rejected by risk engine: {risk_decision.reason}"
            logger.info(f"[4/5] TRADE BLOCKED BY RISK: {summary}")
            run_id = self.audit_logger.log_run(
                market_analysis=market_analysis,
                trade_proposal=trade_proposal,
                adversarial_report=adversarial_report,
                risk_decision=risk_decision,
                stop_reason=summary,
            )
            return PipelineResult(
                run_id=run_id,
                stage_reached="risk",
                executed=False,
                summary=summary,
            )
        
        logger.info(f"[4/5] Risk check PASSED - proceeding to execution")

        # --- Stage 5: Execution ---
        logger.info(f"[5/5] Submitting order to Alpaca...")
        try:
            order_id = self.alpaca_service.submit_vertical_spread(
                long_symbol=trade_proposal.long_symbol,
                short_symbol=trade_proposal.short_symbol,
                quantity=trade_proposal.quantity,
            )
            logger.info(f"[5/5] Order submitted: {order_id}")
            execution_result = self.alpaca_service.poll_order_until_filled(order_id)
            logger.info(
                f"[5/5] Execution result: status={execution_result.status.value}, "
                f"detail={execution_result.detail}"
            )
        except Exception as e:
            logger.error(f"[5/5] Execution failed with exception: {e}", exc_info=True)
            execution_result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                detail=f"Execution raised an unexpected error: {e}",
            )

        if execution_result.status == ExecutionStatus.FILLED:
            realized_loss = 0.0  # unrealized at fill time; loss only realized on close
            self.risk_engine.record_trade_executed(realized_pnl=realized_loss)
            logger.info(f"[5/5] TRADE FILLED - pipeline complete")

        executed = execution_result.status == ExecutionStatus.FILLED
        summary = (
            f"Trade executed: {execution_result.detail}"
            if executed
            else f"Trade approved but did not fill: {execution_result.detail}"
        )

        run_id = self.audit_logger.log_run(
            market_analysis=market_analysis,
            trade_proposal=trade_proposal,
            adversarial_report=adversarial_report,
            risk_decision=risk_decision,
            execution_result=execution_result,
            stop_reason=summary,
        )

        logger.info(f"=== PIPELINE END: executed={executed}, summary={summary} ===")
        return PipelineResult(
            run_id=run_id,
            stage_reached="execution",
            executed=executed,
            summary=summary,
        )