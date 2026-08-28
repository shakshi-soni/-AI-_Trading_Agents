"""
Market Data Service.

Owns the StockHistoricalDataClient connection and any read-only market
data operations (bars, latest quote/trade, volume). This is what
market_agent.py calls into — it should never talk to Alpaca directly.
"""

import os
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame


class MarketDataService:
    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        client: StockHistoricalDataClient | None = None,
    ) -> None:
        """
        Pass an explicit `client` to inject a fake/mock data client for
        testing without hitting the real API.
        """
        if client is not None:
            self.client = client
            return

        api_key = api_key or os.getenv("ALPACA_API_KEY")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")

        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set. "
                "Set them in .env or pass explicitly."
            )

        self.client = StockHistoricalDataClient(api_key, secret_key)

    def get_latest_price(self, symbol: str) -> float:
        """Return the most recent trade price for a symbol."""
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        result = self.client.get_stock_latest_trade(req)

        if symbol not in result:
            raise ValueError(f"No latest trade data returned for {symbol}")

        return float(result[symbol].price)

    def get_recent_bars(
        self,
        symbol: str,
        lookback_days: int = 30,
        timeframe: TimeFrame = TimeFrame.Day,
    ) -> list[dict]:
        """
        Return recent OHLCV bars for a symbol, oldest first. Used by
        market_agent.py to compute momentum/trend/volume signals.
        """
        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
        )
        result = self.client.get_stock_bars(req)

        if symbol not in result.data:
            raise ValueError(f"No bar data returned for {symbol}")

        bars = result.data[symbol]
        return [
            {
                "timestamp": bar.timestamp.isoformat() if hasattr(bar.timestamp, "isoformat") else str(bar.timestamp),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
            }
            for bar in bars
        ]

    def get_average_volume(self, symbol: str, lookback_days: int = 20) -> float:
        """Average daily volume over the lookback window."""
        bars = self.get_recent_bars(symbol, lookback_days=lookback_days)
        if not bars:
            raise ValueError(f"No bars available to compute average volume for {symbol}")
        return sum(b["volume"] for b in bars) / len(bars)

    def get_price_change_pct(self, symbol: str, lookback_days: int = 5) -> float:
        """
        % price change from the oldest close in the window to the latest
        close. Positive = up, negative = down. Used as a simple momentum
        signal for market_agent.py.
        """
        bars = self.get_recent_bars(symbol, lookback_days=lookback_days)
        if len(bars) < 2:
            raise ValueError(
                f"Need at least 2 bars to compute price change for {symbol}, got {len(bars)}"
            )
        first_close = bars[0]["close"]
        last_close = bars[-1]["close"]
        if first_close == 0:
            raise ValueError(f"First close is 0 for {symbol}, cannot compute % change")
        return ((last_close - first_close) / first_close) * 100