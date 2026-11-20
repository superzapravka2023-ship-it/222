import aiohttp
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BYBIT_BASE = "https://api.bybit.com"

# Kline intervals we check
TIMEFRAMES = [
    {"interval": "60",   "hours": 1,    "label": "1 час"},
    {"interval": "120",  "hours": 2,    "label": "2 часа"},
    {"interval": "240",  "hours": 4,    "label": "4 часа"},
    {"interval": "360",  "hours": 6,    "label": "6 часов"},
    {"interval": "720",  "hours": 12,   "label": "12 часов"},
    {"interval": "D",    "hours": 24,   "label": "24 часа"},
    {"interval": "D",    "hours": 36,   "label": "36 часов"},
]


class BybitScanner:
    def __init__(self, db):
        self.db = db
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    async def _get(self, url, params=None):
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data
        except Exception as e:
            logger.error(f"HTTP error {url}: {e}")
            return None

    async def get_all_symbols(self):
        """Get all linear (USDT perpetual) futures symbols"""
        url = f"{BYBIT_BASE}/v5/market/instruments-info"
        data = await self._get(url, {"category": "linear", "limit": 1000})
        if not data or data.get("retCode") != 0:
            return []
        symbols = []
        for item in data["result"]["list"]:
            if item["quoteCoin"] == "USDT" and item["status"] == "Trading":
                symbols.append(item["symbol"])
        return symbols

    async def get_ticker(self, symbol: str):
        """Get 24h ticker for a symbol"""
        url = f"{BYBIT_BASE}/v5/market/tickers"
        data = await self._get(url, {"category": "linear", "symbol": symbol})
        if not data or data.get("retCode") != 0:
            return None
        items = data["result"]["list"]
        if not items:
            return None
        t = items[0]
        return {
            "symbol": symbol,
            "last_price": float(t.get("lastPrice", 0)),
            "volume_24h": float(t.get("turnover24h", 0)),
            "price_24h_pct": float(t.get("price24hPcnt", 0)) * 100,
        }

    async def get_kline(self, symbol: str, interval: str, limit: int = 2):
        """Get kline (OHLCV) data"""
        url = f"{BYBIT_BASE}/v5/market/kline"
        data = await self._get(url, {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })
        if not data or data.get("retCode") != 0:
            return None
        return data["result"]["list"]  # newest first

    async def check_symbol_pump(self, symbol: str, cfg: dict):
        """Check if symbol pumped within configured timeframe"""
        min_tf_h = cfg["min_tf"]
        max_tf_h = cfg["max_tf"]
        min_pct = cfg["min_pct"]

        alerts = []

        # Filter relevant timeframes
        tfs = [tf for tf in TIMEFRAMES if min_tf_h <= tf["hours"] <= max_tf_h]

        for tf in tfs:
            try:
                interval = tf["interval"]
                hours = tf["hours"]

                # For multi-hour checks with D interval, get more candles
                limit = max(2, int(hours / 24) + 1) if interval == "D" else 2

                klines = await self.get_kline(symbol, interval, limit=limit)
                if not klines or len(klines) < 2:
                    continue

                # klines[0] = current/latest, klines[-1] = oldest in range
                current_close = float(klines[0][4])   # close price of current candle
                open_price = float(klines[-1][1])      # open price of oldest candle

                if open_price <= 0:
                    continue

                pct_change = ((current_close - open_price) / open_price) * 100

                if pct_change >= min_pct:
                    ticker = await self.get_ticker(symbol)
                    vol = ticker["volume_24h"] if ticker else 0

                    # Minimum volume filter — skip micro-cap dust
                    if vol < 100_000:
                        continue

                    alerts.append({
                        "symbol": symbol,
                        "pct_change": pct_change,
                        "price": current_close,
                        "open_price": open_price,
                        "timeframe": tf["label"],
                        "hours": hours,
                        "volume_24h": vol,
                        "interval": interval,
                    })
                    break  # one alert per symbol is enough

            except Exception as e:
                logger.debug(f"Error checking {symbol} {tf}: {e}")
                continue

        return alerts

    async def scan(self):
        """Main scan — check all symbols, return list of events"""
        cfg = self.db.get_settings()
        target_pct = cfg["target_pct"]
        results = []

        # 1) Check watchlist — update prices & look for target reached
        watchlist = self.db.get_watchlist()
        for symbol in watchlist:
            try:
                ticker = await self.get_ticker(symbol)
                if not ticker:
                    continue
                current_price = ticker["last_price"]
                self.db.update_watchlist_price(symbol, current_price)
                info = self.db.get_coin_info(symbol)
                if info:
                    pct_total = info["pct_current"]
                    to_target = target_pct - pct_total

                    if pct_total >= target_pct and not info.get("alerted_target"):
                        self.db.mark_target_alerted(symbol)
                        results.append({
                            "type": "target_reached",
                            "symbol": symbol,
                            "pct_total": pct_total,
                            "price": current_price,
                        })
                    elif 0 < to_target <= 10 and not info.get("alerted_near"):
                        # Near target — send update
                        self.db.mark_near_alerted(symbol)
                        results.append({
                            "type": "update",
                            "symbol": symbol,
                            "pct_total": pct_total,
                            "price": current_price,
                            "to_target": to_target,
                        })
            except Exception as e:
                logger.error(f"Watchlist check error {symbol}: {e}")

        # 2) Scan ALL symbols for new pumps
        all_symbols = await self.get_all_symbols()
        logger.info(f"Scanning {len(all_symbols)} symbols...")

        # Batch requests to avoid rate limits
        batch_size = 20
        for i in range(0, len(all_symbols), batch_size):
            batch = all_symbols[i:i + batch_size]
            tasks = [self.check_symbol_pump(sym, cfg) for sym in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for sym_alerts in batch_results:
                if isinstance(sym_alerts, Exception):
                    continue
                for alert in sym_alerts:
                    sym = alert["symbol"]
                    # Skip if already in watchlist
                    if sym in watchlist:
                        continue
                    # Add to watchlist
                    self.db.add_to_watchlist(
                        symbol=sym,
                        price=alert["price"],
                        pct=alert["pct_change"],
                        timeframe=alert["timeframe"],
                    )
                    self.db.increment_found()
                    results.append({
                        "type": "new_pump",
                        **alert,
                    })

            await asyncio.sleep(0.3)  # polite rate limiting

        logger.info(f"Scan complete. {len(results)} events.")
        return results
