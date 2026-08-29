"""
Audit Logger.

Every run of the pipeline produces one JSON file capturing the full
decision trail: market analysis, trade proposal, adversarial report,
risk decision, and execution result. This is what answers "why did
the agent trade" or "why didn't it" — the core of the demo story.

No LLM involvement. Pure file I/O.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class AuditLogger:
    """Writes one JSON audit record per pipeline run to data/audit/."""

    def __init__(self, audit_dir: str = "data/audit") -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _serialize(value):
        """Convert Pydantic models (or None) into plain JSON-safe dicts."""
        if value is None:
            return None
        if isinstance(value, BaseModel):
            return json.loads(value.model_dump_json())
        return value

    def log_run(
        self,
        market_analysis=None,
        trade_proposal=None,
        adversarial_report=None,
        risk_decision=None,
        execution_result=None,
        run_id: str | None = None,
        stop_reason: str | None = None,
    ) -> str:
        """
        Write one audit record. Any stage can be None if the pipeline
        stopped before reaching it (e.g. adversarial rejected the trade,
        so risk_decision and execution_result stay None).

        stop_reason is a plain-English explanation of the outcome (why
        the pipeline stopped, or that it completed) — this is what
        the dashboard shows the user instead of guessing from which
        fields are present/absent.

        Returns the run_id used (generated if not provided) so callers
        can reference the same run elsewhere (e.g. in the dashboard).
        """
        if run_id is None:
            run_id = f"run_{uuid.uuid4().hex[:8]}"

        record = {
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat(),
            "market_analysis": self._serialize(market_analysis),
            "trade_proposal": self._serialize(trade_proposal),
            "adversarial_report": self._serialize(adversarial_report),
            "risk_decision": self._serialize(risk_decision),
            "execution_result": self._serialize(execution_result),
            "stop_reason": stop_reason,
        }

        file_path = self.audit_dir / f"{run_id}.json"
        file_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

        return run_id

    def load_run(self, run_id: str) -> dict:
        """Read back a single run's audit record."""
        file_path = self.audit_dir / f"{run_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"No audit record found for run_id={run_id}")
        return json.loads(file_path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[str]:
        """Return all run_ids currently on disk, most recent first."""
        files = sorted(
            self.audit_dir.glob("run_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [f.stem for f in files]

    def load_all_runs(self) -> list[dict]:
        """Return all audit records, most recent first — used by the dashboard."""
        return [self.load_run(run_id) for run_id in self.list_runs()]