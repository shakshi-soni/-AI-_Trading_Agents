"""
Health Check Script.

Attempts to import every Python module under app/ and reports which
ones import cleanly vs which ones fail, with the exact error for any
failure. Run this from the project root after installing
requirements.txt.

This only checks that files are syntactically valid and their imports
resolve — it does NOT call any real API (Alpaca, Groq, Gemini). For
that, run the actual pipeline via `python -m app.main`.

Usage:
    python check_all_files.py
"""

import importlib
import sys
import traceback
from pathlib import Path

# Modules to check, in dependency order (models first, agents/orchestrator last)
MODULES_TO_CHECK = [
    "app.models.market",
    "app.models.strategy",
    "app.models.adversarial",
    "app.models.risk",
    "app.models.execution",
    "app.risk.risk_engine",
    "app.audit.audit_logger",
    "app.services.alpaca_service",
    "app.services.market_data_service",
    "app.services.options_service",
    "app.agents.market_agent",
    "app.agents.strategy_agent",
    "app.agents.adversarial_agent",
    "app.orchestrator",
    "app.main",
]


def check_module(module_name: str) -> tuple[bool, str]:
    """Attempt to import a module fresh. Returns (success, message)."""
    # Remove from cache if already imported, to force a fresh import
    if module_name in sys.modules:
        del sys.modules[module_name]

    try:
        importlib.import_module(module_name)
        return True, "OK"
    except Exception as e:
        tb = traceback.format_exc()
        return False, f"{type(e).__name__}: {e}\n{tb}"


def main() -> int:
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))

    print("=" * 70)
    print("HEALTH CHECK — importing every module under app/")
    print("=" * 70)

    results = []
    for module_name in MODULES_TO_CHECK:
        success, message = check_module(module_name)
        results.append((module_name, success, message))
        status = "PASS" if success else "FAIL"
        icon = "✅" if success else "❌"
        print(f"{icon} [{status}] {module_name}")
        if not success:
            print(f"   {message.splitlines()[0]}")

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"RESULT: {passed}/{len(results)} modules imported cleanly")

    if failed > 0:
        print(f"\n{failed} module(s) FAILED. Full tracebacks below:\n")
        for module_name, success, message in results:
            if not success:
                print(f"\n--- {module_name} ---")
                print(message)
        print("\nNOTE: A failure often means a missing dependency. Run:")
        print("   pip install -r requirements.txt")
        return 1

    print("\nAll modules import cleanly. This confirms syntax + import")
    print("correctness only — it does NOT confirm real API calls work.")
    print("Next: run `python -m app.main --ticker SPY` to test the real pipeline.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())