"""
Sentinel Dashboard.

Single-page Streamlit UI for the Adversarial Options Trader. Shows
the full decision trail for a pipeline run — market read, proposed
trade, adversarial challenge, risk decision, and execution result —
plus a sidebar to trigger new runs and browse past ones.
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
        }

        .stApp {
            background-color: var(--nude-bg);
        }

        .sentinel-header {
            font-size: 2.1rem;
            font-weight: 700;
            color: var(--nude-text);
            margin-bottom: 0.1rem;
        }
        .sentinel-subheader {
            font-size: 0.95rem;
            color: #8A7A6D;
            margin-bottom: 1.6rem;
        }

        .stage-card {
            background-color: var(--nude-card);
            border: 1px solid var(--nude-border);
            border-radius: 14px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 6px rgba(74, 59, 50, 0.05);
        }
        .stage-title {
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--nude-accent);
            margin-bottom: 0.5rem;
        }
        .stage-empty {
            color: #B5A99B;
            font-style: italic;
            font-size: 0.92rem;
        }

        .badge {
            display: inline-block;
            padding: 0.22rem 0.75rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .badge-good {
            background-color: var(--sage-bg);
            color: var(--sage);
        }
        .badge-bad {
            background-color: var(--terracotta-bg);
            color: var(--terracotta);
        }

        .metric-row {
            display: flex;
            gap: 2rem;
            margin-top: 0.4rem;
        }
        .metric-label {
            font-size: 0.75rem;
            color: #A0917F;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .metric-value {
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--nude-text);
        }

        section[data-testid="stSidebar"] {
            background-color: #F3E9DD;
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


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🛡️ Sentinel")
    st.caption("Adversarial Options Trader")
    st.divider()

    ticker = st.selectbox("Ticker", options=get_watchlist(), key="ticker_select")
    quantity = st.number_input("Quantity", min_value=1, max_value=20, value=1, step=1, key="quantity_input")
    llm_provider = st.radio("LLM Provider", options=list(SUPPORTED_LLM_PROVIDERS), key="llm_provider_radio")

    run_clicked = st.button("▶  Run Analysis", use_container_width=True, key="run_button")

    st.divider()
    st.markdown("**Recent Runs**")

    run_ids = audit_logger.list_runs()
    if run_ids:
        chosen = st.selectbox(
            "Browse past runs",
            options=run_ids,
            key="recent_run_select",
            label_visibility="collapsed",
        )
        if chosen:
            st.session_state.selected_run_id = chosen
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
# Header
# ---------------------------------------------------------------------------
st.markdown('<div class="sentinel-header">🛡️ Sentinel — Adversarial Options Trader</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sentinel-subheader">The AI proposes. The adversary challenges. Code verifies. Alpaca executes.</div>',
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
        st.caption(f"Run ID: `{record['run_id']}`  •  {record['timestamp']}")

        market = record.get("market_analysis")
        proposal = record.get("trade_proposal")
        adversarial = record.get("adversarial_report")
        risk = record.get("risk_decision")
        execution = record.get("execution_result")

        # --- Market ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">📊 Market Analysis</div>', unsafe_allow_html=True)
        if market:
            direction_badge = "badge-good" if market["direction"] == "bullish" else "badge-bad" if market["direction"] == "bearish" else "badge-bad"
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                st.markdown(f'<span class="badge {direction_badge}">{market["direction"].upper()}</span>', unsafe_allow_html=True)
            with col2:
                st.markdown(
                    f'<div class="metric-label">Confidence</div><div class="metric-value">{market["confidence"]*100:.0f}%</div>',
                    unsafe_allow_html=True,
                )
            with col3:
                st.markdown(
                    f'<div class="metric-label">{market["ticker"]} Price</div><div class="metric-value">${market["current_price"]:.2f}</div>',
                    unsafe_allow_html=True,
                )
            if market.get("evidence"):
                st.markdown("&nbsp;")
                for e in market["evidence"]:
                    st.markdown(f"- {e}")
        else:
            st.markdown('<div class="stage-empty">No market analysis recorded.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Proposed Trade ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">📝 Proposed Trade</div>', unsafe_allow_html=True)
        if proposal:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(
                    f'<div class="metric-label">Strategy</div><div class="metric-value">{proposal["strategy"].replace("_", " ").title()}</div>',
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    f'<div class="metric-label">Strikes</div><div class="metric-value">{proposal["long_strike"]:.0f} / {proposal["short_strike"]:.0f}</div>',
                    unsafe_allow_html=True,
                )
            with col3:
                st.markdown(
                    f'<div class="metric-label">Max Loss</div><div class="metric-value">${proposal["max_loss"]:.2f}</div>',
                    unsafe_allow_html=True,
                )
            with col4:
                st.markdown(
                    f'<div class="metric-label">Max Profit</div><div class="metric-value">${proposal["max_profit"]:.2f}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("&nbsp;")
            st.markdown(f"*{proposal['rationale']}*")
        else:
            st.markdown(
                '<div class="stage-empty">No trade proposed — market read did not support a bullish spread.</div>',
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Adversarial Attack ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">⚔️ Adversarial Challenge</div>', unsafe_allow_html=True)
        if adversarial:
            badge_class = "badge-good" if adversarial["verdict"] == "survive" else "badge-bad"
            col1, col2 = st.columns([1, 3])
            with col1:
                st.markdown(f'<span class="badge {badge_class}">{adversarial["verdict"].upper()}</span>', unsafe_allow_html=True)
            with col2:
                st.markdown(
                    f'<div class="metric-label">Thesis Survival</div><div class="metric-value">{adversarial["thesis_survival"]*100:.0f}%</div>',
                    unsafe_allow_html=True,
                )
            st.markdown("&nbsp;")
            if adversarial.get("weaknesses"):
                st.markdown("**Weaknesses raised:**")
                for w in adversarial["weaknesses"]:
                    st.markdown(f"- ⚠️ {w}")
            if adversarial.get("strengths"):
                st.markdown("**Strengths held:**")
                for s in adversarial["strengths"]:
                    st.markdown(f"- ✓ {s}")
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
                icon = "✓" if check["passed"] else "✗"
                st.markdown(f"{icon} **{check['rule']}** — {check['detail']}")
        else:
            st.markdown('<div class="stage-empty">Pipeline stopped before reaching the risk engine.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Final Decision ---
        st.markdown('<div class="stage-card">', unsafe_allow_html=True)
        st.markdown('<div class="stage-title">🏁 Final Decision</div>', unsafe_allow_html=True)
        if execution:
            status = execution["status"]
            badge_class = "badge-good" if status == "filled" else "badge-bad"
            st.markdown(f'<span class="badge {badge_class}">{status.upper().replace("_", " ")}</span>', unsafe_allow_html=True)
            st.markdown("&nbsp;")
            if execution.get("order_id"):
                st.markdown(f"**Order ID:** `{execution['order_id']}`")
            if execution.get("filled_avg_price") is not None:
                st.markdown(f"**Filled avg price:** ${execution['filled_avg_price']:.2f}")
            st.markdown(f"{execution.get('detail', '')}")
        else:
            st.markdown('<div class="stage-empty">No trade reached execution.</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)