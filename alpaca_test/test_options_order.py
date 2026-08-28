"""
Phase 0 — Alpaca Options Execution Proof.

Goal: prove, end to end, that this Alpaca paper account can:
  1. Connect to the Trading API
  2. Find valid option contracts for an underlying
  3. Build a vertical spread (bull call spread) from those contracts
  4. Submit it as a single multi-leg (MLeg) order
  5. See it get accepted and filled

Nothing else in this project gets built until this script runs clean.
If it fails, stop and fix Alpaca before writing any agent code.
"""

import os
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    MarketOrderRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import (
    AssetStatus,
    ContractType,
    ExerciseStyle,
    OrderClass,
    OrderSide,
    OrderStatus,
    OrderType,
    QueryOrderStatus,
    TimeInForce,
)

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

UNDERLYING = "SPY"          # liquid, always has a deep options chain
SPREAD_WIDTH_STRIKES = 2    # how many strikes wide the spread should be
MIN_DAYS_TO_EXPIRY = 14     # avoid anything expiring too soon
MAX_DAYS_TO_EXPIRY = 45     # avoid anything too far out
FILL_POLL_SECONDS = 3
FILL_POLL_MAX_ATTEMPTS = 20  # ~1 minute of polling


def fail(msg: str) -> None:
    print(f"\n🛑 STOP — {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def step(msg: str) -> None:
    print(f"\n→ {msg}")


def main() -> None:
    # ---------------------------------------------------------------
    # 0. Sanity check environment
    # ---------------------------------------------------------------
    step("Checking environment variables")
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        fail(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not set. "
            "Copy .env.example to .env and fill in your paper trading keys."
        )
    if not ALPACA_PAPER:
        fail(
            "ALPACA_PAPER is not 'true'. This script will only run against "
            "a PAPER account. Refusing to continue against what looks like "
            "a live account."
        )
    ok("Environment variables present, paper mode confirmed")

    # ---------------------------------------------------------------
    # 1. Connect
    # ---------------------------------------------------------------
    step("Connecting to Alpaca Trading API")
    client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

    try:
        account = client.get_account()
    except Exception as e:
        fail(f"Could not connect / authenticate to Alpaca: {e}")

    ok(f"Connected. Account status: {account.status}")
    print(f"   Buying power: ${account.buying_power}")
    print(f"   Options trading level: {getattr(account, 'options_trading_level', 'n/a')}")

    if str(account.status) != "AccountStatus.ACTIVE":
        fail(f"Account is not ACTIVE (status={account.status}). Fix this in the Alpaca dashboard first.")

    options_level = getattr(account, "options_trading_level", None)
    if options_level is not None and int(options_level) < 3:
        fail(
            f"Account's options trading level is {options_level}, but multi-leg "
            "(spread) orders require Level 3. Enable Level 3 options trading "
            "in the Alpaca paper dashboard before continuing."
        )
    ok("Options trading level supports multi-leg orders")

    # ---------------------------------------------------------------
    # 2. Get current price of the underlying (to pick sensible strikes)
    # ---------------------------------------------------------------
    step(f"Fetching a recent quote for {UNDERLYING} to anchor strike selection")
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest

        stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
        latest_trade = stock_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=UNDERLYING)
        )
        underlying_price = float(latest_trade[UNDERLYING].price)
    except Exception as e:
        fail(f"Could not fetch underlying price for {UNDERLYING}: {e}")

    ok(f"{UNDERLYING} last trade price: ${underlying_price:.2f}")

    # ---------------------------------------------------------------
    # 3. Find a valid, liquid expiration + call contracts around the price
    # ---------------------------------------------------------------
    step("Searching for call option contracts near the current price")
    today = datetime.now().date()
    exp_gte = today + timedelta(days=MIN_DAYS_TO_EXPIRY)
    exp_lte = today + timedelta(days=MAX_DAYS_TO_EXPIRY)

    # Cast a slightly wide net around the current price so we have
    # enough strikes on either side to build a spread.
    strike_low = underlying_price * 0.97
    strike_high = underlying_price * 1.05

    try:
        contracts_req = GetOptionContractsRequest(
            underlying_symbols=[UNDERLYING],
            status=AssetStatus.ACTIVE,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            strike_price_gte=str(round(strike_low, 2)),
            strike_price_lte=str(round(strike_high, 2)),
            type=ContractType.CALL,
            style=ExerciseStyle.AMERICAN,
        )
        contracts_resp = client.get_option_contracts(contracts_req)
        contracts = contracts_resp.option_contracts
    except Exception as e:
        fail(f"get_option_contracts failed: {e}")

    if not contracts or len(contracts) < SPREAD_WIDTH_STRIKES + 1:
        fail(
            f"Not enough call contracts found for {UNDERLYING} in the "
            f"{MIN_DAYS_TO_EXPIRY}-{MAX_DAYS_TO_EXPIRY} day window "
            f"(found {len(contracts) if contracts else 0}). Widen the "
            "strike/expiry window and retry."
        )

    # Sort by strike so we can pick two nearby strikes to spread across.
    contracts_sorted = sorted(contracts, key=lambda c: float(c.strike_price))

    # Pick the contract with the strike nearest to (but at/above) current
    # price as our long leg, and one a few strikes higher as the short leg.
    long_idx = next(
        (i for i, c in enumerate(contracts_sorted) if float(c.strike_price) >= underlying_price),
        0,
    )
    short_idx = min(long_idx + SPREAD_WIDTH_STRIKES, len(contracts_sorted) - 1)

    if short_idx == long_idx:
        fail("Could not find a distinct higher strike for the short leg. Widen the strike window.")

    long_contract = contracts_sorted[long_idx]
    short_contract = contracts_sorted[short_idx]

    ok(
        f"Selected bull call spread: BUY {long_contract.symbol} "
        f"(strike {long_contract.strike_price}) / "
        f"SELL {short_contract.symbol} (strike {short_contract.strike_price}), "
        f"expiry {long_contract.expiration_date}"
    )

    # ---------------------------------------------------------------
    # 4. Build the multi-leg order (this IS the vertical spread)
    # ---------------------------------------------------------------
    step("Building multi-leg (MLeg) order request")
    legs = [
        OptionLegRequest(
            symbol=long_contract.symbol,
            side=OrderSide.BUY,
            ratio_qty=1,
        ),
        OptionLegRequest(
            symbol=short_contract.symbol,
            side=OrderSide.SELL,
            ratio_qty=1,
        ),
    ]

    order_req = MarketOrderRequest(
        qty=1,
        order_class=OrderClass.MLEG,
        type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        legs=legs,
    )
    ok("Order request built")

    # ---------------------------------------------------------------
    # 5. Submit
    # ---------------------------------------------------------------
    step("Submitting paper order to Alpaca")
    try:
        order = client.submit_order(order_req)
    except Exception as e:
        fail(f"submit_order failed: {e}")

    ok(f"Order submitted. id={order.id} status={order.status}")

    # ---------------------------------------------------------------
    # 6. Poll for fill
    # ---------------------------------------------------------------
    step("Polling order status until filled (or terminal failure)")
    terminal_bad = {
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
        OrderStatus.REJECTED,
        OrderStatus.SUSPENDED,
    }

    final_order = order
    for attempt in range(1, FILL_POLL_MAX_ATTEMPTS + 1):
        final_order = client.get_order_by_id(order.id)
        print(f"   [{attempt}/{FILL_POLL_MAX_ATTEMPTS}] status={final_order.status}")

        if final_order.status == OrderStatus.FILLED:
            break
        if final_order.status in terminal_bad:
            fail(f"Order reached a terminal failure state: {final_order.status}")

        time.sleep(FILL_POLL_SECONDS)
    else:
        fail(
            f"Order did not fill within {FILL_POLL_MAX_ATTEMPTS * FILL_POLL_SECONDS}s "
            f"(last status: {final_order.status}). Paper fills are usually fast — "
            "check market hours and contract liquidity."
        )

    ok(f"Order FILLED. id={final_order.id}")

    # ---------------------------------------------------------------
    # 7. Confirm the resulting position
    # ---------------------------------------------------------------
    step("Checking resulting positions")
    try:
        positions = client.get_all_positions()
    except Exception as e:
        fail(f"get_all_positions failed: {e}")

    relevant = [p for p in positions if p.symbol in (long_contract.symbol, short_contract.symbol)]
    if not relevant:
        fail("Order filled but no matching positions found. Something is off — investigate before building further.")

    for p in relevant:
        print(f"   {p.symbol}: qty={p.qty} side={p.side} avg_entry_price={p.avg_entry_price}")

    print("\n" + "=" * 60)
    print("✅ GREEN LIGHT — Phase 0 complete.")
    print("Alpaca paper options spread execution is confirmed working.")
    print("Safe to proceed to building the full project structure.")
    print("=" * 60)


if __name__ == "__main__":
    main()