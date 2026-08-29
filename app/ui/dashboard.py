"""
Sentinel Dashboard.

Single-page Streamlit UI for the Adversarial Options Trader. Shows a
header status bar, a pipeline stepper (Market -> Strategy -> Adversary
-> Risk -> Execution), a hero "Final Decision" card, and the full
decision trail underneath. Sidebar lets you trigger new runs and
browse past ones.
"""

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from app.audit.audit_logger import AuditLogger
from app.main import ConfigError, SUPPORTED_LLM_PROVIDERS, build_orchestrator

st.set_page_config(
    page_title="Sentinel — Adversarial Options Trader",
    page_icon="🛡️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Theme / styling — light, nude palette
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
        :root {
            --nude-bg: #FDF8F3;
            --nude-card: #FFFFFF;
            --nude-border: #E9DCC9;
            --nude-accent: #B08968;
            --nude-text: #4A3B32;
            --sage: #7C9070;
            --sage-bg: #EEF2E8;
            --terracotta: #C1694F;
            --terracotta-bg: #FBEAE3;
            --muted: #B5A99B;
        }

        .stApp { background-color: var(--nude-bg); }

        /* --- Top status bar --- */
        .topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.9rem 1.4rem;
            background-color: var(--nude-card);
            border: 1px solid var(--nude-border);
            border-radius: 14px;
            margin-bottom: 1.2rem;
        }
        .topbar-left { display: flex; flex-direction: column; }
        .topbar-title {
            font-size: 1.4rem;
            font-weight: 800;
            color: var(--nude-text);
            letter-spacing: 0.01em;
        }
        .topbar-subtitle { font-size: 0.82rem; color: #8A7A6D; }
        .topbar-right { display: flex; gap: 0.7rem; }
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.32rem 0.85rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            background-color: var(--sage-bg);
            color: var(--sage);
        }
        .status-pill.off { background-color: #F1EDE7; color: var(--muted); }
        .status-dot {
            width: 8px; height: 8px; border-radius: 50%;
            background-color: var(--sage);
            display: inline-block;
        }
        .status-dot.off { background-color: var(--muted); }

        /* --- Ticker price row --- */
        .ticker-row {
            display: flex;
            align-items: baseline;
            gap: 1.2rem;
            margin-bottom: 1rem;
        }
        .ticker-symbol { font-size: 1.6rem; font-weight: 800; color: var(--nude-text); }
        .ticker-price { font-size: 1.6rem; font-weight: 700; color: var(--nude-text); }
        .ticker-meta { font-size: 0.8rem; color: #A0917F; margin-left: auto; text-align: right; }

        /* --- Pipeline stepper --- */
        .stepper {
            display: flex;
            justify-content: space-between;
            background-color: var(--nude-card);
            border: 1px solid var(--nude-border);
            border-radius: 14px;
            padding: 0.9rem 1.4rem;
            margin-bottom: 1.2rem;
        }
        .step { display: flex; flex-direction: column; align-items: center; gap: 0.35rem; flex: 1; }
        .step-label { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; color: #A0917F; }
        .step-icon { font-size: 1.15rem; font-weight: 800; }
        .step-icon.ok { color: var(--sage); }
        .step-icon.bad { color: var(--terracotta); }
        .step-icon.pending { color: var(--muted); }

        /* --- Hero decision card --- */
        .hero-card {
            border-radius: 16px;
            padding: 1.6rem 1.8rem;
            margin-bottom: 1.2rem;
            text-align: center;
            border: 1px solid var(--nude-border);
        }
        .hero-approved { background-color: var(--sage-bg); border-color: var(--sage); }
        .hero-rejected { background-color: var(--terracotta-bg); border-color: var(--terracotta); }
        .hero-neutral { background-color: var(--nude-card); }
        .hero-label { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.1em; color: #A0917F; margin-bottom: 0.3rem; }
        .hero-verdict { font-size: 1.55rem; font-weight: 800; margin-bottom: 0.5rem; }
        .hero-verdict.ok { color: var(--sage); }
        .hero-verdict.bad { color: var(--terracotta); }
        .hero-verdict.neutral { color: var(--nude-text); }
        .hero-strategy { font-size: 1rem; color: var(--nude-text); margin-bottom: 0.3rem; }
        .hero-rr { font-size: 0.92rem; color: #8A7A6D; }

        /* --- Stage cards --- */
        .stage-card {
            background-color: var(--nude-card);
            border: 1px solid var(--nude-border);
            border-radius: 14px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 6px rgba(74, 59, 50, 0.05);
        }
        .stage-title {
            font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: var(--nude-accent); margin-bottom: 0.6rem;
        }
        .stage-empty { color: var(--muted); font-style: italic; font-size: 0.92rem; }

        .badge {
            display: inline-block; padding: 0.22rem 0.75rem; border-radius: 999px;
            font-size: 0.8rem; font-weight: 700;
        }
        .badge-good { background-color: var(--sage-bg); color: var(--sage); }
        .badge-bad { background-color: var(--terracotta-bg); color: var(--terracotta); }

        .metric-label { font-size: 0.72rem; color: #A0917F; text-transform: uppercase; letter-spacing: 0.05em; }
        .metric-value { font-size: 1.1rem; font-weight: 700; color: var(--nude-text); }

        .leg-row { font-size: 0.95rem; color: var(--nude-text); margin: 0.15rem 0; }
        .leg-buy { color: var(--sage); font-weight: 700; }
        .leg-sell { color: var(--terracotta); font-weight: 700; }

        .risk-row { font-size: 0.9rem; margin: 0.3rem 0; }
        .risk-ok::before { content: "✓  "; color: var(--sage); font-weight: 800; }
        .risk-bad::before { content: "✗  "; color: var(--terracotta); font-weight: 800; }

        section[data-testid="stSidebar"] { background-color: #F3E9DD; }
        .sidebar-section-title {
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; color: #8A7A6D; margin: 0.6rem 0 0.3rem 0;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
audit_logger = AuditLogger()

if "selected_run_id" not in st.session_state:
    st.session_state.selected_run_id = None
if "last_error" not in st.session_state:
    st.session_state.last_error = None


def get_watchlist() -> list[str]:
    raw = os.getenv("WATCHLIST", "SPY,QQQ,NVDA,AAPL,MSFT")
    symbols = [s.strip() for s in raw.split(",") if s.strip()]
    return symbols or ["SPY"]


def short_id(run_id: str) -> str:
    """Shorten run_<hex> -> #<first 4 hex chars uppercased>, matching the mockup's compact style."""
    tail = run_id.replace("run_", "")
    return f"#{tail[:4].upper()}" if tail else run_id


# ---------------------------------------------------------------------------
# Sidebar — CONTROL
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛡️ Sentinel")
    st.caption("Adversarial Options Trader")
    st.markdown('<div class="sidebar-section-title">Control</div>', unsafe_allow_html=True)

    ticker = st.selectbox("Ticker", options=get_watchlist(), key="ticker_select")
    quantity = st.number_input("Quantity", min_value=1, max_value=20, value=1, step=1, key="quantity_input")
    llm_provider = st.radio("LLM Provider", options=list(SUPPORTED_LLM_PROVIDERS), key="llm_provider_radio")

    run_clicked = st.button("▶  Run Analysis", use_container_width=True, key="run_button")

    st.markdown('<div class="sidebar-section-title">Recent Runs</div>', unsafe_allow_html=True)

    run_ids = audit_logger.list_runs()
    if run_ids:
        for rid in run_ids[:10]:
            is_selected = rid == st.session_state.selected_run_id
            label = f"{'●' if is_selected else '○'} {short_id(rid)}"
            if st.button(label, key=f"recent_{rid}", use_container_width=True):
                st.session_state.selected_run_id = rid
    else:
        st.caption("No runs yet.")

# ---------------------------------------------------------------------------
# Handle "Run Analysis" click
# ---------------------------------------------------------------------------
if run_clicked:
    st.session_state.last_error = None
    with st.spinner(f"Running pipeline for {ticker}..."):
        try:
            orchestrator = build_orchestrator(llm_provider)
            result = orchestrator.run(ticker, quantity=quantity)
            st.session_state.selected_run_id = result.run_id
        except ConfigError as e:
            st.session_state.last_error = f"Configuration error: {e}"
        except Exception as e:
            st.session_state.last_error = f"Pipeline run failed: {e}"

# ---------------------------------------------------------------------------
# Top status bar
# ---------------------------------------------------------------------------
paper_mode = os.getenv("ALPACA_PAPER", "true").lower() == "true"
alpaca_configured = bool(os.getenv("ALPACA_API_KEY"))

paper_pill_class = "status-pill" if paper_mode else "status-pill off"
paper_dot_class = "status-dot" if paper_mode else "status-dot off"
alpaca_pill_class = "status-pill" if alpaca_configured else "status-pill off"
alpaca_dot_class = "status-dot" if alpaca_configured else "status-dot off"

st.markdown(
    f"""
    <div class="topbar">
        <div class="topbar-left">
            <div class="topbar-title">🛡️ SENTINEL</div>
            <div class="topbar-subtitle">Adversarial Options Intelligence</div>
        </div>
        <div class="topbar-right">
            <span class="{paper_pill_class}" title="Reads ALPACA_PAPER from environment">
                <span class="{paper_dot_class}"></span> PAPER TRADING
            </span>
            <span class="{alpaca_pill_class}" title="Based on ALPACA_API_KEY being set — not a live connection check">
                <span class="{alpaca_dot_class}"></span> ALPACA
            </span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.last_error:
    st.error(st.session_state.last_error)

# ---------------------------------------------------------------------------
# Main content — render the selected run
# ---------------------------------------------------------------------------
if not st.session_state.selected_run_id:
    st.info("No run selected yet. Choose a ticker in the sidebar and click **Run Analysis** to get started.")
else:
    try:
        record = audit_logger.load_run(st.session_state.selected_run_id)
    except FileNotFoundError:
        st.error(f"Run '{st.session_state.selected_run_id}' not found.")
        record = None

    if record:
        market = record.get("market_analysis")
        proposal = record.get("trade_proposal")
        adversarial = record.get("adversarial_report")
        risk = record.get("risk_decision")
        execution = record.get("execution_result")

        # --- Ticker price row ---
        if market:
            st.markdown(
                f"""
                <div class="ticker-row">
                    <span class="ticker-symbol">{market['ticker']}</span>
                    <span class="ticker-price">${market['current_price']:.2f}</span>
                    <span class="ticker-meta">RUN {short_id(record['run_id'])} &nbsp;•&nbsp; {record['timestamp']}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # --- Pipeline stepper ---
        def step_icon(reached: bool, ok: bool | None) -> str:
            if not reached:
                return '<span class="step-icon pending">–</span>'
            if ok is True:
                return '<span class="step-icon ok">✓</span>'
            if ok is False:
                return '<span class="step-icon bad">✗</span>'
            return '<span class="step-icon pending">–</span>'

        market_reached = market is not None
        strategy_reached = proposal is not None
        adversarial_reached = adversarial is not None
        risk_reached = risk is not None
        execution_reached = execution is not None

        adversarial_ok = adversarial["verdict"] == "survive" if adversarial else None
        risk_ok = risk["verdict"] == "pass" if risk else None
        execution_ok = execution["status"] == "filled" if execution else None

        st.markdown(
            f"""
            <div class="stepper">
                <div class="step"><div class="step-label">MARKET</div>{step_icon(market_reached, True if market_reached else None)}</div>
                <div class="step"><div class="step-label">STRATEGY</div>{step_icon(strategy_reached, True if strategy_reached else None)}</div>
                <div class="step"><div class="step-label">ADVERSARY</div>{step_icon(adversarial_reached, adversarial_ok)}</div>
                <div class="step"><div class="step-label">RISK</div>{step_icon(risk_reached, risk_ok)}</div>
                <div class="step"><div class="step-label">EXECUTION</div>{step_icon(execution_reached, execution_ok)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # --- Hero: Final Decision ---
        if execution and execution["status"] == "filled":
            hero_class, verdict_class, verdict_text = "hero-approved", "ok", "✓ TRADE APPROVED"
        elif execution and execution["status"] in ("rejected", "failed"):
            hero_class, verdict_class, verdict_text = "hero-rejected", "bad", "✗ EXECUTION FAILED"
        elif risk and risk["verdict"] == "fail":
            hero_class, verdict_class, verdict_text = "hero-rejected", "bad", "✗ REJECTED BY RISK ENGINE"
        elif adversarial and adversarial["verdict"] == "reject":
            hero_class, verdict_class, verdict_text = "hero-rejected", "bad", "✗ REJECTED BY ADVERSARY"
        elif proposal is None:
            hero_class, verdict_class, verdict_text = "hero-neutral", "neutral", "– NO TRADE PROPOSED"
        else:
            hero_class, verdict_class, verdict_text = "hero-neutral", "neutral", "– PENDING"

        strategy_line = ""
        rr_line = ""
        if proposal:
            strategy_line = f'<div class="hero-strategy">{proposal["strategy"].replace("_", " ").title()}</div>'
            rr_line = f'<div class="hero-rr">Risk: ${proposal["max_loss"]:.0f} &nbsp;&nbsp; Reward: ${proposal["max_profit"]:.0f}</div>'

        stop_reason = record.get("stop_reason")
        reason_line = ""
        if stop_reason and verdict_class != "ok":
            reason_line = f'<div class="hero-rr" style="margin-top:0.5rem;">{stop_reason}</div>'

        st.markdown(
            f"""
            <div class="hero-card {hero_class}">
                <div class="hero-label">FINAL DECISION</div>
                <div class="hero-verdict {verdict_class}">{verdict_text}</div>
                {strategy_line}
                {rr_line}
                {reason_line}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # --- Market + Proposed Trade side by side ---
        col_market, col_trade = st.columns([1, 1.4])

        with col_market:
            st.markdown('<div class="stage-card">', unsafe_allow_html=True)
            st.markdown('<div class="stage-title">📊 Market</div>', unsafe_allow_html=True)
            if market:
                badge_class = "badge-good" if market["direction"] == "bullish" else "badge-bad"
                st.markdown(f'<span class="badge {badge_class}">{market["direction"].upper()}</span>', unsafe_allow_html=True)
                st.markdown("&nbsp;")
                st.markdown(
                    f'<div class="metric-label">Confidence</div><div class="metric-value">{market["confidence"]*100:.0f}%</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="metric-label">Price</div><div class="metric-value">${market["current_price"]:.2f}</div>',
                    unsafe_allow_html=True,
                )
                if market.get("evidence"):
                    st.markdown("&nbsp;")
                    for e in market["evidence"]:
                        st.markdown(f"- {e}")
            else:
                st.markdown('<div class="stage-empty">No market analysis recorded.</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with col_trade:
            st.markdown('<div class="stage-card">', unsafe_allow_html=True)
            st.markdown('<div class="stage-title">📝 Proposed Options Trade</div>', unsafe_allow_html=True)
            if proposal:
                st.markdown(f"**{proposal['ticker']} {proposal['strategy'].replace('_', ' ').title()}**")
                st.markdown(
                    f'<div class="leg-row"><span class="leg-buy">BUY</span> &nbsp;${proposal["long_strike"]:.0f} CALL</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="leg-row"><span class="leg-sell">SELL</span> ${proposal["short_strike"]:.0f} CALL</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("&nbsp;")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(
                        f'<div class="metric-label">Max Loss</div><div class="metric-value">${proposal["max_loss"]:.2f}</div>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        f'<div class="metric-label">Max Profit</div><div class="metric-value">${proposal["max_profit"]:.2f}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown("&nbsp;")
                st.markdown(f"*{proposal['rationale']}*")
            else:
                fallback = "No trade was proposed for this run."
                st.markdown(
                    f'<div class="stage-empty">{stop_reason or fallback}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)

        # --- Adversarial Challenge ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">⚔️ Adversarial Challenge</div>', unsafe_allow_html=True)
        if adversarial:
            badge_class = "badge-good" if adversarial["verdict"] == "survive" else "badge-bad"
            verdict_label = "THESIS SURVIVED" if adversarial["verdict"] == "survive" else "THESIS REJECTED"
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f'<span class="badge {badge_class}">{verdict_label}</span>', unsafe_allow_html=True)
            with col2:
                st.markdown(
                    f'<div class="metric-label">Thesis Survival</div><div class="metric-value">{adversarial["thesis_survival"]*100:.0f}%</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("&nbsp;")
            for s in adversarial.get("strengths", []):
                st.markdown(f"✓ {s}")
            for w in adversarial.get("weaknesses", []):
                st.markdown(f"⚠ {w}")
            st.markdown(f"*{adversarial['reasoning']}*")
        else:
            st.markdown('<div class="stage-empty">Pipeline stopped before reaching the adversarial challenge.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Risk Engine ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">🛡️ Risk Engine</div>', unsafe_allow_html=True)
        if risk:
            badge_class = "badge-good" if risk["verdict"] == "pass" else "badge-bad"
            st.markdown(f'<span class="badge {badge_class}">{risk["verdict"].upper()}</span>', unsafe_allow_html=True)
            st.markdown("&nbsp;")
            for check in risk.get("checks", []):
                row_class = "risk-row risk-ok" if check["passed"] else "risk-row risk-bad"
                rule_label = check["rule"].replace("_", " ").title()
                st.markdown(
                    f'<div class="{row_class}"><strong>{rule_label}</strong> — {check["detail"]}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown('<div class="stage-empty">Pipeline stopped before reaching the risk engine.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Execution ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">🏁 Execution</div>', unsafe_allow_html=True)
        if execution:
            status = execution["status"]
            badge_class = "badge-good" if status == "filled" else "badge-bad"
            status_label = "PAPER ORDER FILLED" if status == "filled" else status.upper().replace("_", " ")
            st.markdown(f'<span class="badge {badge_class}">{status_label}</span>', unsafe_allow_html=True)
            st.markdown("&nbsp;")
            if execution.get("order_id"):
                st.markdown(f"**Order ID:** `{execution['order_id']}`")
            if execution.get("filled_avg_price") is not None:
                st.markdown(f"**Avg Price:** ${execution['filled_avg_price']:.2f}")
            st.markdown(f"{execution.get('detail', '')}")
        else:
            st.markdown('<div class="stage-empty">No trade reached execution.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)