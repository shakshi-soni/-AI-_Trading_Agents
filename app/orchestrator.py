"""
Orchestrator.

Controls the sequence: Market Agent -> Strategy Agent -> Adversarial
Agent -> Risk Engine -> Execution -> Audit. Contains no trading logic
itself — every decision is made by the component responsible for it.
This file only sequences calls and decides whether to continue or
stop based on each component's verdict.
"""

from dataclasses import dataclass

from app.agents.adversarial_agent import AdversarialAgent
from app.agents.market_agent import MarketAgent
from app.agents.strategy_agent import StrategyAgent, StrategyAgentError
from app.audit.audit_logger import AuditLogger
from app.models.adversarial import AdversarialVerdict
from app.models.execution import ExecutionResult, ExecutionStatus
from app.models.risk import RiskVerdict
from app.risk.risk_engine import RiskEngine
from app.services.alpaca_service import AlpacaService


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

        # --- Stage 1: Market Agent ---
        market_analysis = self.market_agent.analyze(ticker)

        # --- Stage 2: Strategy Agent ---
        # A non-bullish call is a valid, expected outcome (not an error) —
        # the pipeline simply stops here with no trade proposed.
        try:
            trade_proposal = self.strategy_agent.propose(market_analysis, quantity=quantity)
        except StrategyAgentError as e:
            run_id = self.audit_logger.log_run(market_analysis=market_analysis)
            return PipelineResult(
                run_id=run_id,
                stage_reached="market",
                executed=False,
                summary=f"No trade proposed: {e}",
            )

        # --- Stage 3: Adversarial Agent ---
        adversarial_report = self.adversarial_agent.attack(trade_proposal, market_analysis)

        if adversarial_report.verdict == AdversarialVerdict.REJECT:
            run_id = self.audit_logger.log_run(
                market_analysis=market_analysis,
                trade_proposal=trade_proposal,
                adversarial_report=adversarial_report,
            )
            return PipelineResult(
                run_id=run_id,
                stage_reached="adversarial",
                executed=False,
                summary=f"Trade rejected by adversarial agent: {adversarial_report.reasoning}",
            )

        # --- Stage 4: Risk Engine ---
        risk_decision = self.risk_engine.evaluate(trade_proposal)

        if risk_decision.verdict == RiskVerdict.FAIL:
            run_id = self.audit_logger.log_run(
                market_analysis=market_analysis,
                trade_proposal=trade_proposal,
                adversarial_report=adversarial_report,
                risk_decision=risk_decision,
            )
            return PipelineResult(
                run_id=run_id,
                stage_reached="risk",
                executed=False,
                summary=f"Trade rejected by risk engine: {risk_decision.reason}",
            )

        # --- Stage 5: Execution ---
        try:
            order_id = self.alpaca_service.submit_vertical_spread(
                long_symbol=trade_proposal.long_symbol,
                short_symbol=trade_proposal.short_symbol,
                quantity=trade_proposal.quantity,
            )
            execution_result = self.alpaca_service.poll_order_until_filled(order_id)
        except Exception as e:
            execution_result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                detail=f"Execution raised an unexpected error: {e}",
            )

        if execution_result.status == ExecutionStatus.FILLED:
            realized_loss = 0.0  # unrealized at fill time; loss only realized on close
            self.risk_engine.record_trade_executed(realized_pnl=realized_loss)

        run_id = self.audit_logger.log_run(
            market_analysis=market_analysis,
            trade_proposal=trade_proposal,
            adversarial_report=adversarial_report,
            risk_decision=risk_decision,
            execution_result=execution_result,
        )

        executed = execution_result.status == ExecutionStatus.FILLED
        summary = (
            f"Trade executed: {execution_result.detail}"
            if executed
            else f"Trade approved but did not fill: {execution_result.detail}"
        )

        return PipelineResult(
            run_id=run_id,
            stage_reached="execution",
            executed=executed,
            summary=summary,
        )