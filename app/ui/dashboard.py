"""
Sentinel Dashboard.

Single-page Streamlit UI for the Adversarial Options Trader, styled
as a dark quantitative trading terminal. Uses real st.container(
border=True, key=...) blocks for cards (not raw HTML <div> wrapping,
which does not visually nest Streamlit-rendered content and produces
empty-looking boxes) so every card genuinely encloses its content.
"""

import logging
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# Setup logging for better debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
# Theme — dark quantitative trading terminal
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
        :root {
            --bg: #080B12;
            --panel: #0F141D;
            --panel-2: #131A24;
            --border: #263241;
            --text: #F4F7FA;
            --text-secondary: #8C98A8;
            --text-muted: #5F6B7A;
            --success: #20D39B;
            --success-bg: #0D2B24;
            --danger: #FF5C6C;
            --danger-bg: #32151C;
            --warning: #F5B84B;
            --warning-bg: #30230F;
            --exec-blue: #4DB8FF;
            --exec-bg: #10283A;
            --accent: #7C8CFF;
        }

        .stApp { background-color: var(--bg); color: var(--text); }
        section[data-testid="stSidebar"] {
            background-color: var(--panel);
            border-right: 1px solid var(--border);
        }
        section[data-testid="stSidebar"] * { color: var(--text) !important; }
        section[data-testid="stSidebar"] label { color: var(--text-secondary) !important; }

        /* Make default Streamlit text readable on dark bg */
        .stMarkdown, .stMarkdown p, .stCaption, p, span, label { color: var(--text); }

        /* Buttons */
        .stButton > button {
            background-color: var(--panel-2);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: 10px;
            font-weight: 600;
        }
        .stButton > button:hover {
            border-color: var(--accent);
            color: var(--accent);
        }
        div[data-testid="stSidebar"] .stButton > button[kind="primary"],
        .st-key-run_button button {
            background-color: var(--accent) !important;
            color: #0A0E14 !important;
            border: none !important;
            font-weight: 700;
        }

        /* Bordered containers (our cards) — target by stable .st-key-<name> class */
        div[class*="st-key-card_"] {
            background-color: var(--panel) !important;
            border: 1px solid var(--border) !important;
            border-radius: 12px !important;
        }
        div[class*="st-key-hero_"] {
            border-radius: 14px !important;
        }

        /* Top status bar */
        .topbar {
            display: flex; justify-content: space-between; align-items: center;
            padding: 0.9rem 1.4rem; background-color: var(--panel);
            border: 1px solid var(--border); border-radius: 12px; margin-bottom: 1rem;
        }
        .topbar-title { font-size: 1.35rem; font-weight: 800; color: var(--text); }
        .topbar-subtitle { font-size: 0.8rem; color: var(--text-secondary); }
        .status-pill {
            display: inline-flex; align-items: center; gap: 0.4rem;
            padding: 0.3rem 0.8rem; border-radius: 999px; font-size: 0.72rem;
            font-weight: 700; letter-spacing: 0.04em;
            background-color: var(--success-bg); color: var(--success);
        }
        .status-pill.off { background-color: var(--panel-2); color: var(--text-muted); }
        .status-dot { width: 7px; height: 7px; border-radius: 50%; background-color: var(--success); display: inline-block; }
        .status-dot.off { background-color: var(--text-muted); }

        /* Ticker row */
        .ticker-symbol { font-size: 1.5rem; font-weight: 800; color: var(--text); }
        .ticker-price { font-size: 1.5rem; font-weight: 700; color: var(--text); margin-left: 0.8rem; }
        .ticker-meta { font-size: 0.78rem; color: var(--text-muted); }

        /* Pipeline stepper */
        .step-label { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; color: var(--text-secondary); text-align: center; }
        .step-icon { font-size: 1.05rem; font-weight: 800; text-align: center; display: block; }
        .step-icon.ok { color: var(--success); }
        .step-icon.bad { color: var(--danger); }
        .step-icon.pending { color: var(--text-muted); }
        .step-state { font-size: 0.65rem; text-align: center; display: block; letter-spacing: 0.05em; }
        .step-state.ok { color: var(--success); }
        .step-state.bad { color: var(--danger); }
        .step-state.pending { color: var(--text-muted); }

        /* Hero */
        .hero-label { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.1em; color: var(--text-secondary); text-align: center; }
        .hero-verdict { font-size: 1.5rem; font-weight: 800; text-align: center; margin: 0.3rem 0; }
        .hero-verdict.ok { color: var(--success); }
        .hero-verdict.bad { color: var(--danger); }
        .hero-verdict.warn { color: var(--warning); }
        .hero-strategy { font-size: 1rem; color: var(--text); text-align: center; }
        .hero-rr { font-size: 0.9rem; color: var(--text-secondary); text-align: center; margin-top: 0.3rem; }
        .hero-error-box {
            background-color: var(--warning-bg); border: 1px solid var(--warning);
            border-radius: 8px; padding: 0.7rem 1rem; margin-top: 0.7rem;
            font-size: 0.85rem; color: var(--text); text-align: left;
        }

        /* Section titles inside cards */
        .card-title { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); margin-bottom: 0.5rem; }
        .stage-empty { color: var(--text-muted); font-style: italic; font-size: 0.88rem; }
        .metric-label { font-size: 0.68rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; }
        .metric-value { font-size: 1.05rem; font-weight: 700; color: var(--text); }

        .badge { display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
        .badge-good { background-color: var(--success-bg); color: var(--success); }
        .badge-bad { background-color: var(--danger-bg); color: var(--danger); }
        .badge-exec { background-color: var(--exec-bg); color: var(--exec-blue); }

        .leg-row { font-size: 0.92rem; color: var(--text); margin: 0.1rem 0; }
        .leg-buy { color: var(--success); font-weight: 700; }
        .leg-sell { color: var(--danger); font-weight: 700; }

        .risk-row { font-size: 0.87rem; margin: 0.25rem 0; color: var(--text); }
        .risk-ok::before { content: "✓  "; color: var(--success); font-weight: 800; }
        .risk-bad::before { content: "✗  "; color: var(--danger); font-weight: 800; }

        /* Sidebar input styling — dark theme for selectbox, number_input, radio buttons */
        section[data-testid="stSidebar"] input[type="text"],
        section[data-testid="stSidebar"] input[type="number"],
        section[data-testid="stSidebar"] select,
        section[data-testid="stSidebar"] [data-testid="stSelectbox"] > div,
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] input {
            background-color: var(--panel-2) !important;
            color: var(--text) !important;
            border: 1px solid var(--border) !important;
            border-radius: 6px !important;
            padding: 0.5rem !important;
            font-size: 0.9rem !important;
        }

        section[data-testid="stSidebar"] input[type="text"]::placeholder,
        section[data-testid="stSidebar"] input[type="number"]::placeholder {
            color: var(--text-muted) !important;
        }

        section[data-testid="stSidebar"] input[type="text"]:focus,
        section[data-testid="stSidebar"] input[type="number"]:focus {
            background-color: var(--panel-2) !important;
            border-color: var(--accent) !important;
            color: var(--text) !important;
            box-shadow: 0 0 0 2px rgba(124, 140, 255, 0.2) !important;
        }

        /* Selectbox dropdown styling */
        section[data-testid="stSidebar"] [data-baseweb="select"] {
            background-color: var(--panel-2) !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="select"] > div {
            background-color: var(--panel-2) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
        }

        section[data-testid="stSidebar"] [role="listbox"],
        section[data-testid="stSidebar"] [data-baseweb="menu"] {
            background-color: var(--panel) !important;
            color: var(--text) !important;
        }

        section[data-testid="stSidebar"] [role="option"],
        section[data-testid="stSidebar"] li[role="option"] {
            background-color: var(--panel) !important;
            color: var(--text) !important;
        }

        section[data-testid="stSidebar"] [role="option"]:hover,
        section[data-testid="stSidebar"] li[role="option"]:hover {
            background-color: var(--panel-2) !important;
            color: var(--accent) !important;
        }

        /* Number input increment/decrement buttons */
        section[data-testid="stSidebar"] [data-testid="stNumberInput"] button {
            background-color: var(--panel-2) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
        }

        section[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover {
            background-color: var(--panel) !important;
            color: var(--accent) !important;
        }

        /* Radio button styling */
        section[data-testid="stSidebar"] [data-testid="stRadio"] label {
            color: var(--text) !important;
        }

        section[data-testid="stSidebar"] [data-testid="stRadio"] input[type="radio"] + label {
            color: var(--text-secondary) !important;
        }

        section[data-testid="stSidebar"] [data-testid="stRadio"] input[type="radio"]:checked + label {
            color: var(--accent) !important;
            font-weight: 600 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    tail = run_id.replace("run_", "")
    return f"#{tail[:4].upper()}" if tail else run_id


# ---------------------------------------------------------------------------
# Sidebar — CONTROL
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛡️ Sentinel")
    st.caption("Adversarial Options Trader")
    st.markdown("**CONTROL**")

    ticker = st.selectbox("Ticker", options=get_watchlist(), key="ticker_select")
    quantity = st.number_input("Quantity", min_value=1, max_value=20, value=1, step=1, key="quantity_input")
    llm_provider = st.radio("LLM Provider", options=list(SUPPORTED_LLM_PROVIDERS), key="llm_provider_radio")

    run_clicked = st.button("▶  RUN ANALYSIS", use_container_width=True, key="run_button")

    st.markdown("**RECENT RUNS**")
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

paper_pill = "status-pill" if paper_mode else "status-pill off"
paper_dot = "status-dot" if paper_mode else "status-dot off"
alpaca_pill = "status-pill" if alpaca_configured else "status-pill off"
alpaca_dot = "status-dot" if alpaca_configured else "status-dot off"

st.markdown(
    f"""
    <div class="topbar">
        <div>
            <div class="topbar-title">🛡️ SENTINEL</div>
            <div class="topbar-subtitle">Adversarial Options Intelligence</div>
        </div>
        <div>
            <span class="{paper_pill}" title="Reads ALPACA_PAPER from environment">
                <span class="{paper_dot}"></span> PAPER TRADING
            </span>
            &nbsp;
            <span class="{alpaca_pill}" title="Based on ALPACA_API_KEY being set — not a live connection check">
                <span class="{alpaca_dot}"></span> ALPACA
            </span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.last_error:
    st.error(st.session_state.last_error)

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------
if not st.session_state.selected_run_id:
    st.info("No run selected yet. Choose a ticker in the sidebar and click **RUN ANALYSIS** to get started.")
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
        stop_reason = record.get("stop_reason")

        # --- Ticker price row ---
        if market:
            c1, c2, c3 = st.columns([2, 2, 3])
            with c1:
                st.markdown(f'<span class="ticker-symbol">{market["ticker"]}</span>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<span class="ticker-price">${market["current_price"]:.2f}</span>', unsafe_allow_html=True)
            with c3:
                st.markdown(
                    f'<div class="ticker-meta" style="text-align:right;">RUN {short_id(record["run_id"])} &nbsp;•&nbsp; {record["timestamp"]}</div>',
                    unsafe_allow_html=True,
                )

        st.write("")

        # --- Pipeline stepper ---
        def stage_state(reached: bool, ok: bool | None) -> tuple[str, str]:
            """Returns (icon_html, state_label)."""
            if not reached:
                return "–", "NOT RUN"
            if ok is True:
                return "✓", "PASSED"
            if ok is False:
                return "✕", "REJECTED"
            return "–", "RUNNING"

        market_reached = market is not None
        strategy_reached = proposal is not None
        adversarial_reached = adversarial is not None
        risk_reached = risk is not None
        execution_reached = execution is not None

        adversarial_ok = adversarial["verdict"] == "survive" if adversarial else None
        risk_ok = risk["verdict"] == "pass" if risk else None
        execution_ok = execution["status"] == "filled" if execution else None

        stages = [
            ("MARKET", *stage_state(market_reached, True if market_reached else None)),
            ("STRATEGY", *stage_state(strategy_reached, True if strategy_reached else None)),
            ("ADVERSARY", *stage_state(adversarial_reached, adversarial_ok)),
            ("RISK", *stage_state(risk_reached, risk_ok)),
            ("EXECUTION", *stage_state(execution_reached, execution_ok)),
        ]

        step_cols = st.columns(5)
        for col, (label, icon, state) in zip(step_cols, stages):
            css_class = "ok" if state in ("PASSED", "COMPLETE") else "bad" if state in ("REJECTED", "BLOCKED") else "pending"
            with col:
                st.markdown(
                    f'<div class="step-label">{label}</div>'
                    f'<div class="step-icon {css_class}">{icon}</div>'
                    f'<div class="step-state {css_class}">{state}</div>',
                    unsafe_allow_html=True,
                )

        st.write("")

        # --- Hero: Final Decision ---
        if execution and execution["status"] == "filled":
            verdict_class, verdict_text = "ok", "✓ TRADE FILLED"
        elif execution and execution["status"] in ("rejected", "failed"):
            verdict_class, verdict_text = "bad", "✕ EXECUTION FAILED"
        elif risk and risk["verdict"] == "fail":
            verdict_class, verdict_text = "bad", "✕ REJECTED BY RISK ENGINE"
        elif adversarial and adversarial["verdict"] == "reject":
            verdict_class, verdict_text = "bad", "✕ REJECTED BY ADVERSARY"
        elif strategy_reached and not adversarial_reached:
            verdict_class, verdict_text = "warn", "⚠ AWAITING ADVERSARIAL REVIEW"
        elif market_reached and not strategy_reached:
            verdict_class, verdict_text = "warn", "⚠ STRATEGY NOT PROPOSED"
        elif not market_reached:
            verdict_class, verdict_text = "warn", "⚠ MARKET ANALYSIS INCOMPLETE"
        else:
            verdict_class, verdict_text = "warn", "⚠ PIPELINE IN PROGRESS"

        with st.container(border=True, key="hero_card"):
            st.markdown(f'<div class="hero-label">FINAL DECISION</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="hero-verdict {verdict_class}">{verdict_text}</div>', unsafe_allow_html=True)
            if proposal:
                st.markdown(f'<div class="hero-strategy">{proposal["strategy"].replace("_", " ").title()}</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="hero-rr">Risk ${proposal["max_loss"]:.0f} &nbsp;&nbsp; Reward ${proposal["max_profit"]:.0f}</div>',
                    unsafe_allow_html=True,
                )
            if stop_reason and verdict_class != "ok":
                st.markdown(f'<div class="hero-error-box">{stop_reason}</div>', unsafe_allow_html=True)

        st.write("")

        # --- Market + Proposed Trade side by side ---
        col_market, col_trade = st.columns([1, 1.4])

        with col_market:
            with st.container(border=True, key="card_market"):
                st.markdown('<div class="card-title">📊 Market</div>', unsafe_allow_html=True)
                if market:
                    badge_class = "badge-good" if market["direction"] == "bullish" else "badge-bad"
                    st.markdown(f'<span class="badge {badge_class}">{market["direction"].upper()}</span>', unsafe_allow_html=True)
                    st.write("")
                    st.markdown(
                        f'<div class="metric-label">Confidence</div><div class="metric-value">{market["confidence"]*100:.0f}%</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div class="metric-label">Price</div><div class="metric-value">${market["current_price"]:.2f}</div>',
                        unsafe_allow_html=True,
                    )
                    if market.get("evidence"):
                        st.write("")
                        for e in market["evidence"]:
                            st.markdown(f"- {e}")
                else:
                    st.markdown('<div class="stage-empty">No market analysis recorded.</div>', unsafe_allow_html=True)

        with col_trade:
            with st.container(border=True, key="card_trade"):
                st.markdown('<div class="card-title">📝 Proposed Options Trade</div>', unsafe_allow_html=True)
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
                    expiry_text = proposal.get("expiration")
                    if expiry_text:
                        st.markdown(f"**Expiration:** {expiry_text}")
                    st.write("")
                    
                    # Show verified economics if available
                    use_verified = proposal.get("verified_max_loss") and proposal.get("verified_max_profit")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        max_loss = proposal.get("verified_max_loss", proposal["max_loss"])
                        label = "Max Loss (Verified)" if use_verified else "Max Loss (LLM)"
                        st.markdown(
                            f'<div class="metric-label">{label}</div><div class="metric-value">${max_loss:.2f}</div>',
                            unsafe_allow_html=True,
                        )
                    with c2:
                        max_profit = proposal.get("verified_max_profit", proposal["max_profit"])
                        label = "Max Profit (Verified)" if use_verified else "Max Profit (LLM)"
                        st.markdown(
                            f'<div class="metric-label">{label}</div><div class="metric-value">${max_profit:.2f}</div>',
                            unsafe_allow_html=True,
                        )
                    
                    st.write("")
                    st.markdown(f"*{proposal['rationale']}*")
                    
                    # Show verification warnings if any
                    if proposal.get("verification_warnings"):
                        st.write("")
                        st.markdown("**Validation Warnings:**")
                        for warning in proposal.get("verification_warnings", []):
                            st.markdown(f"⚠ {warning}")
                else:
                    fallback = "No trade was proposed for this run."
                    st.markdown(f'<div class="stage-empty">{stop_reason or fallback}</div>', unsafe_allow_html=True)

        # --- Adversarial Challenge ---
        with st.container(border=True, key="card_adversarial"):
            st.markdown('<div class="card-title">⚔️ Adversarial Challenge</div>', unsafe_allow_html=True)
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
                
                # Show verified facts separately
                st.write("")
                st.markdown("**Trade Facts Supplied to Adversary:**")
                verified = adversarial.get("verified_facts", {})
                if verified:
                    facts_cols = st.columns(3)
                    with facts_cols[0]:
                        st.markdown(f'<div class="metric-label">Max Loss</div><div class="metric-value">${verified.get("max_loss", 0):.2f}</div>', unsafe_allow_html=True)
                    with facts_cols[1]:
                        st.markdown(f'<div class="metric-label">Max Profit</div><div class="metric-value">${verified.get("max_profit", 0):.2f}</div>', unsafe_allow_html=True)
                    with facts_cols[2]:
                        st.markdown(f'<div class="metric-label">Breakeven</div><div class="metric-value">${verified.get("breakeven_price", 0):.2f}</div>', unsafe_allow_html=True)
                    st.markdown(f"DTE: {verified.get('days_to_expiration', 0)} | Expiration: {verified.get('expiration', 'n/a')} | Spread: ${verified.get('spread_width', 0):.2f}")
                
                # Show adversarial arguments
                st.write("")
                st.markdown("**Adversarial Analysis:**")
                for s in adversarial.get("strengths", []):
                    st.markdown(f"✓ {s}")
                for w in adversarial.get("weaknesses", []):
                    st.markdown(f"⚠ {w}")
                st.markdown(f"*{adversarial['reasoning']}*")
            else:
                st.markdown('<div class="stage-empty">Strategy proposal required before adversarial validation.</div>', unsafe_allow_html=True)

        # --- Risk Engine ---
        with st.container(border=True, key="card_risk"):
            st.markdown('<div class="card-title">🛡️ Risk Engine</div>', unsafe_allow_html=True)
            if risk:
                badge_class = "badge-good" if risk["verdict"] == "pass" else "badge-bad"
                st.markdown(f'<span class="badge {badge_class}">{risk["verdict"].upper()}</span>', unsafe_allow_html=True)
                st.write("")
                for check in risk.get("checks", []):
                    row_class = "risk-row risk-ok" if check["passed"] else "risk-row risk-bad"
                    rule_label = check["rule"].replace("_", " ").title()
                    st.markdown(f'<div class="{row_class}"><strong>{rule_label}</strong> — {check["detail"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="stage-empty">Adversarial approval required before risk validation.</div>', unsafe_allow_html=True)

        # --- Execution ---
        with st.container(border=True, key="card_execution"):
            st.markdown('<div class="card-title">🏁 Execution</div>', unsafe_allow_html=True)
            if execution:
                status = execution["status"]
                badge_class = "badge-exec" if status == "filled" else "badge-bad"
                status_label = "PAPER ORDER FILLED" if status == "filled" else status.upper().replace("_", " ")
                st.markdown(f'<span class="badge {badge_class}">{status_label}</span>', unsafe_allow_html=True)
                st.write("")
                if execution.get("order_id"):
                    st.markdown(f"**Order ID:** `{execution['order_id']}`")
                
                # Display execution vs. verified economics reconciliation
                if execution.get("filled_avg_price") is not None and proposal:
                    filled_price = execution.get("filled_avg_price")
                    verified_debit = proposal.get("verified_net_debit")
                    
                    st.markdown(f"**Filled Avg Price:** ${filled_price:.2f}")
                    
                    if verified_debit is not None:
                        # Show the expected vs actual debit
                        variance = filled_price - verified_debit
                        variance_pct = (variance / verified_debit * 100) if verified_debit != 0 else 0
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Expected Debit:** ${verified_debit:.2f}")
                        with col2:
                            variance_indicator = "✓ Better" if variance < 0 else "⚠ Worse" if variance > 0 else "="
                            st.markdown(f"**Variance:** {variance_indicator} ${abs(variance):.2f} ({abs(variance_pct):.1f}%)")
                        
                        # Recalculate actual P&L based on filled price
                        spread_width = proposal.get("verified_spread_width", 0)
                        quantity = proposal.get("quantity", 1)
                        if spread_width > 0:
                            actual_max_profit = (spread_width - filled_price) * 100 * quantity
                            actual_max_loss = filled_price * 100 * quantity
                            
                            st.write("")
                            st.markdown("**Actual Economics at Fill:**")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown(f"Max Loss: ${actual_max_loss:.0f}")
                            with col2:
                                st.markdown(f"Max Profit: ${actual_max_profit:.0f}")
                detail = execution.get('detail', '')
                if detail:
                    # Improve readability of error details
                    if "Execution raised an unexpected error:" in detail:
                        # Extract error details
                        error_start = detail.find("{")
                        if error_start > -1:
                            error_end = detail.rfind("}")
                            if error_end > -1:
                                try:
                                    import json
                                    error_json = json.loads(detail[error_start:error_end+1])
                                    st.markdown(f"**Error:** {error_json.get('message', 'Unknown error')}")
                                    if "code" in error_json:
                                        st.markdown(f"*Error Code: {error_json['code']}*")
                                except json.JSONDecodeError:
                                    st.markdown(f"**Status:** {detail}")
                            else:
                                st.markdown(f"**Status:** {detail}")
                        else:
                            st.markdown(f"**Status:** {detail}")
                    else:
                        st.markdown(f"**Status:** {detail}")
            else:
                st.markdown('<div class="stage-empty">Risk approval required before execution.</div>', unsafe_allow_html=True)