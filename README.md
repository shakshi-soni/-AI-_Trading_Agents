# 🛡️ SENTINEL — Adversarial Options Intelligence

**SENTINEL isn't an AI that trades. It's a control protocol that decides whether an AI-generated trade is allowed to reach the broker.**

[![🚀 Live Demo](https://img.shields.io/badge/🚀_Live_Demo-Streamlit-FF4B4B?style=for-the-badge)](https://h9zkctvwtrw6uzqpdyqsjz.streamlit.app/)
[![💻 GitHub](https://img.shields.io/badge/💻_GitHub-Repository-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/shakshi-soni/-AI-_Trading_Agents)
[![Status](https://img.shields.io/badge/Status-Hackathon_MVP-success?style=for-the-badge)]()
[![Broker](https://img.shields.io/badge/Broker-Alpaca_Paper_Trading-yellow?style=for-the-badge)](https://alpaca.markets/)

**🔗 [Launch SENTINEL Live →](https://h9zkctvwtrw6uzqpdyqsjz.streamlit.app/)**

> ⚠️ **TODO before you submit:** replace every `< FILL IN >` placeholder below with your real numbers/screenshots. Judges catch invented statistics fast — an honest small number beats a polished fake one.

---

## ⚡ SENTINEL In One Breath

AI can propose a trade. AI can challenge a trade. **AI cannot authorize a trade.** Only deterministic Python code can — and only Alpaca's paper account ever receives an order. Every step is logged, so any decision can be replayed end-to-end.

---

## 🔬 Proof of Execution

**Example run — NVDA Bull Call Spread**

```
MARKET ✓  →  STRATEGY ✓  →  ADVERSARY ✓  →  RISK ✓  →  ALPACA ✓  →  PAPER FILL
```

| Field | Value |
|---|---|
| Ticker | NVDA |
| Direction | Bullish · 80% confidence |
| Strategy | BUY $220 CALL / SELL $225 CALL |
| Expiration | 2026-09-14 |
| **Proposed** economics (pre-trade estimate) | Max Loss ≈ $175 · Max Profit ≈ $325 · Breakeven ≈ $221.75 |
| **Actual** fill economics (from Alpaca) | `< FILL IN from your real execution/audit record >` |
| Risk gate | PASS ($175 estimate < $500 max risk) |
| Execution | **PAPER ORDER FILLED** ✅ |

> **Important implementation detail:** proposed trade economics are calculated *before* execution by the Strategy Agent. Final, authoritative economics come from the actual Alpaca fill and are reconciled against the proposal in the audit record. If a number above still says "proposed," treat it as an estimate — not a settled trade outcome — until it's reconciled against the fill.

**[📸 Insert your real execution screenshot here]**

---

## 🛑 SENTINEL Can Refuse to Trade

SENTINEL is not built to maximize the number of orders placed — it's built to only place orders that survive every gate. A run can terminate at any stage:

```
MARKET ✕                                  → NO TRADE
MARKET ✓  STRATEGY ✕                      → NO TRADE
MARKET ✓  STRATEGY ✓  ADVERSARY ✕         → NO TRADE
MARKET ✓  STRATEGY ✓  ADVERSARY ✓  RISK ✕ → NO TRADE
MARKET ✓  STRATEGY ✓  ADVERSARY ✓  RISK ✓ → EXECUTE
```

**Example rejected run:** `< FILL IN a real logged example where the adversary or risk engine rejected a trade >`

---

## 🚨 The Problem

A conventional AI trading pipeline looks like this:

```
Market Data → LLM → Trade → Broker
```

The flaw: the same reasoning process generates a thesis and then justifies its own thesis — inviting confirmation bias, overconfidence, invalid structures, poor risk/reward, uncontrolled sizing, and weak auditability.

**SENTINEL separates decision authority from reasoning capability.**

> AI can propose. AI can challenge. **AI cannot authorize.** Code authorizes. Alpaca executes.

---

## 🧬 Architecture

```
                 ┌─────────────────────────┐
                 │     ALPACA DATA API     │
                 │ Market + Options + Acct │
                 └────────────┬────────────┘
                              ↓
                    ┌───────────────────┐
                    │   MARKET AGENT    │
                    │ AI interpretation │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │  STRATEGY AGENT   │
                    │ Trade proposal    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ ADVERSARIAL AGENT │
                    │ Thesis challenge  │
                    └─────────┬─────────┘
                              ↓
              ┌───────────────────────────────┐
              │     DETERMINISTIC CONTROL     │
              │                               │
              │ Trade Validator               │
              │ Risk Engine                   │
              │ Position / Loss Limits        │
              └───────────────┬───────────────┘
                              │
                         PASS / FAIL
                              ↓
                    ┌───────────────────┐
                    │ ALPACA EXECUTION  │
                    │ Multi-leg Options │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │   AUDIT LEDGER    │
                    │ Full decision +   │
                    │ execution trail   │
                    └───────────────────┘
```

### 01 · 🧭 Market Agent
Determines bullish / bearish / neutral direction, a confidence score, current price, and supporting evidence. (MVP supports bullish → bull call spreads.)

### 02 · ♟️ Strategy Agent
Constructs a defined-risk options strategy. Strike/contract selection is handled by `options_service.py`; the LLM estimates the net debit %, which `trade_validation.py` strictly enforces to be `0 < debit < 1` — a real vertical spread can never cost $0 or the full spread width.

### 03 · ⚔️ Adversarial Agent
Instead of asking *"Should I take this trade?"*, a separate reasoning stage asks:

> **"Why is this trade wrong?"**

It challenges market confidence, strike structure, expiration, max loss/profit, risk/reward, breakeven, and time-to-expiration, returning `THESIS SURVIVAL`, `STRENGTHS`, `WEAKNESSES`, `REASONING`, and a `VERDICT`.

Its output is a **challenge signal**, not a veto — that verdict is then evaluated alongside the deterministic structural and risk policies below, which hold final authority.

### 04 · 🛑 Deterministic Risk Engine
No LLM decides whether a trade is financially allowed. Plain, auditable Python logic does:

| Rule | Default |
|---|---|
| 💰 Max risk per trade | `max_loss ≤ $500` |
| 📦 Max position size | `position_size ≤ $5,000` |
| 🔁 Max daily trades | `trades_today < 5` |
| 📉 Max daily loss | `realized_loss_today + this_trade_max_loss ≤ $1,000` |
| ✅ Risk/reward sanity | `max_loss > 0` and `max_profit > 0` |

Output: **PASS** or **FAIL**. No persuasion, no exceptions.

### 05 · 🏦 Execution
Only after Market ✓ → Strategy ✓ → Adversary ✓ → Risk ✓ does SENTINEL reach execution. `alpaca_service.py` builds a multi-leg order (buy long call / sell short call), submits it as an MLeg market order, and polls until a terminal state.

---

## 🧠 AI vs. Deterministic Control

| Component | AI-driven? | Responsibility |
|---|:---:|---|
| Market Agent | ✅ | Market interpretation |
| Strategy Agent | ✅ | Trade thesis / rationale |
| Options Service | ❌ | Contract / strike construction |
| Adversarial Agent | ✅ | Challenge the thesis |
| Trade Validation | ❌ | Financial consistency checks |
| Risk Engine | ❌ | Hard risk authorization |
| Alpaca Service | ❌ | Broker communication |
| Audit Logger | ❌ | Evidence persistence |

**The LLM never receives authority to directly place an order or override a risk rule.**

---

## 🔐 Execution Boundary

The LLM does **not** receive:

- 🚫 Alpaca credentials
- 🚫 Direct broker access
- 🚫 Arbitrary order parameters
- 🚫 Permission to bypass risk checks
- 🚫 Permission to modify risk limits

The execution path is strictly:

```
LLM output → Pydantic model → Deterministic validation → Risk Engine → Alpaca Service → Paper Account
```

---

## 🔌 Built Around Alpaca

SENTINEL uses Alpaca as the **execution boundary**, not a simulated broker. The system uses Alpaca's trading infrastructure to:

- Retrieve market and account information
- Validate options trading readiness
- Construct multi-leg options orders (spreads)
- Submit paper orders
- Poll order state to a terminal result
- Record execution results in the audit trail

SENTINEL currently operates **exclusively in paper trading**. This matters for judges: SENTINEL isn't producing hypothetical trades on paper — there's an actual broker-facing execution layer behind every approved decision.

---

## 🧯 Failure Handling

SENTINEL fails **closed**, not open, when:

- Market data is unavailable
- An LLM response cannot be parsed
- A strategy cannot be constructed
- A trade fails validation
- Risk limits are exceeded
- Alpaca rejects an order
- An order does not reach a successful terminal state

No failed stage is silently converted into an approval.

---

## 🗂️ Full Auditability

Every decision is recorded end-to-end:

```json
{
  "run_id": "A77F",
  "ticker": "NVDA",
  "market": "BULLISH",
  "confidence": 0.80,
  "strategy": "bull_call_spread",
  "adversarial_score": 0.60,
  "risk": {
    "max_loss": 175,
    "position_size": 175,
    "daily_trades": 0
  },
  "decision": "APPROVED",
  "execution": "PAPER_FILLED"
}
```

Any judge can trace: `Market evidence → Trade thesis → Adversarial challenge → Risk decision → Order → Fill`

---

## 📊 System Validation

> Fill this in with real numbers only — do not estimate or round up.

```
Strategy proposals tested        < FILL IN >
Structurally invalid trades      < FILL IN >
Adversarial rejections           < FILL IN >
Risk rejections                  < FILL IN >
Orders submitted                 < FILL IN >
Orders filled                    < FILL IN >

Automated tests passing          < FILL IN > / < FILL IN >
```

Even a modest, real number (e.g. "23 automated tests passing") is stronger evidence than a large invented one.

---

## 📂 Project Structure

```
.
├── .github/workflows/
│   └── main.yml
├── alpaca_test/
│   ├── .env.example
│   ├── requirements.txt
│   └── test_options_order.py
├── app/
│   ├── agents/
│   │   ├── adversarial_agent.py     # ⚔️ Challenges the trade thesis
│   │   ├── market_agent.py          # 🧭 Direction, confidence, evidence
│   │   └── strategy_agent.py        # ♟️ Builds the options spread
│   ├── audit/
│   │   └── audit_logger.py          # 🗂️ Records the full decision chain
│   ├── models/
│   │   ├── adversarial.py
│   │   ├── execution.py
│   │   ├── market.py
│   │   ├── risk.py
│   │   ├── strategy.py
│   │   └── trade_validation.py
│   ├── risk/
│   │   └── risk_engine.py           # 🛑 Deterministic PASS/FAIL gate
│   ├── services/
│   │   ├── alpaca_service.py        # 🏦 Broker connectivity & order routing
│   │   ├── market_data_service.py
│   │   └── options_service.py       # Strike/contract selection
│   ├── ui/
│   │   └── dashboard.py             # 🖥️ Streamlit interface
│   ├── main.py                      # 🚀 App entry point
│   └── orchestrator.py              # 🔗 Wires the full pipeline together
├── data/audit/
├── tests/
│   ├── test_adversarial_missing_reasoning.py
│   └── test_financial_consistency.py
├── .env.example
├── .gitignore
├── check_all_files.py
├── requirements.txt
├── wake_up.py
└── README.md
```

---

## 🧱 Technology Stack

| Layer | Technology |
|---|---|
| 🐍 Language | Python |
| 🖥️ UI | Streamlit |
| 🧠 LLM Reasoning | LLM API via callable abstraction |
| 🛑 Risk | Custom deterministic Python Risk Engine |
| 🏦 Broker | Alpaca (Paper Trading) |
| 📈 Options Execution | Alpaca Trading API / Python SDK |
| 📐 Data Models | Pydantic |
| 🗂️ Persistence / Audit | JSON audit data |
| ☁️ Deployment | Streamlit Community Cloud |

---

## 🚀 Getting Started

```bash
git clone https://github.com/shakshi-soni/-AI-_Trading_Agents
cd -- -AI-_Trading_Agents

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

1. Configure your environment variables in `.env` — see `.env.example` for the required Alpaca and LLM API keys.
2. Launch the app:

```bash
streamlit run app/main.py
```

> ✅ Verify this works from a clean/incognito browser before submission.

**🔗 Or try the hosted version — no setup required:**
### 👉 [**Launch SENTINEL Live**](https://h9zkctvwtrw6uzqpdyqsjz.streamlit.app/) 👈

---

## ⚠️ Current Limitations

SENTINEL is intentionally an MVP. Current limitations include:

- Bull Call Spread strategy only
- Paper trading only — no live-money deployment
- No claim of profitability or statistically significant alpha
- Limited historical strategy validation
- Proposed economics require reconciliation against actual execution prices (see Proof of Execution above)
- No production-grade portfolio optimization

---

## 💡 What Makes SENTINEL Different

❌ Not: *"An AI trading bot."*
✅ **"An adversarial decision protocol for AI-powered options trading."**

The innovation isn't having multiple agents — it's the strict separation of proposal, challenge, enforcement, and execution:

```
LLM proposes
LLM challenges
CODE validates
CODE authorizes
Alpaca executes
```

---

## 🎤 The 30-Second Pitch

> "SENTINEL is an adversarial options trading agent. It doesn't allow the same AI that proposes a trade to be its final authority. A Market Agent analyzes the market, a Strategy Agent constructs a defined-risk options spread, and a separate Adversarial Agent challenges that thesis. Its verdict is then evaluated alongside a deterministic Python Risk Engine that checks hard limits like maximum loss, position size, and daily loss. Only then does SENTINEL send the multi-leg options order to Alpaca's paper account. Every stage is recorded, so every decision is auditable.
>
> The result isn't an AI that simply trades — it's a governed decision pipeline where every transition to execution must satisfy explicit controls."

### 🏆 Tagline

> **"AI can generate a trade. SENTINEL asks whether it deserves to be executed."**

---

## 🙋‍♂️ About the Developer

Built with ❤️ by **[SHAKSHI SONI]**

I'm a developer passionate about building practical AI applications that solve real-world problems. This project explores agentic AI design — where an LLM doesn't just chat, but *acts*, by calling tools, remembering context, and making decisions autonomously.
---

📫 **Connect with me:**
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=flat&logo=linkedin)](https://www.linkedin.com/in/shakshi-soni-961048411/)


<p align="center">
Built with 🛡️ reasoning, ⚔️ challenge, and 🛑 discipline.
</p>
