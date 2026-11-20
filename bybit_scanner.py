import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)
BYBIT = "https://api.bybit.com"

TIMEFRAMES = [
    {"interval": "60",  "hours": 1,  "label": "1 час"},
    {"interval": "120", "hours": 2,  "label": "2 часа"},
    {"interval": "240", "hours": 4,  "label": "4 часа"},
    {"interval": "360", "hours": 6,  "label": "6 часов"},
    {"interval": "720", "hours": 12, "label": "12 часов"},
    {"interval": "D",   "hours": 24, "label": "24 часа"},
    {"interval": "D",   "hours": 36, "label": "36 часов"},
]


class BybitScanner:
    def __init__(self, db):
        self.db = db
        self._session = None

    async def _sess(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )
        return self._session

    async def _get(self, path, **params):
        s = await self._sess()
        try:
            async with s.get(f"{BYBIT}{path}", params=params) as r:
                return await r.json()
        except Exception as e:
            logger.debug(f"bybit GET {path} error: {e}")
            return None

    async def all_symbols(self):
        d = await self._get("/v5/market/instruments-info", category="linear", limit=1000)
        if not d or d.get("retCode") != 0:
            return []
        return [
            i["symbol"] for i in d["result"]["list"]
            if i["quoteCoin"] == "USDT" and i["status"] == "Trading"
        ]

    async def ticker(self, symbol):
        d = await self._get("/v5/market/tickers", category="linear", symbol=symbol)
        if not d or d.get("retCode") != 0:
            return None
        items = d["result"]["list"]
        if not items:
            return None
        t = items[0]
        return {
            "last_price": float(t.get("lastPrice", 0)),
            "volume_24h": float(t.get("turnover24h", 0)),
        }

    async def kline(self, symbol, interval, limit=2):
        d = await self._get("/v5/market/kline",
                            category="linear", symbol=symbol,
                            interval=interval, limit=limit)
        if not d or d.get("retCode") != 0:
            return None
        return d["result"]["list"]

    async def check_pump(self, symbol, cfg):
        min_tf, max_tf, min_pct = cfg["min_tf"], cfg["max_tf"], cfg["min_pct"]
        tfs = [tf for tf in TIMEFRAMES if min_tf <= tf["hours"] <= max_tf]
        for tf in tfs:
            try:
                limit = max(2, int(tf["hours"] / 24) + 1) if tf["interval"] == "D" else 2
                klines = await self.kline(symbol, tf["interval"], limit)
                if not klines or len(klines) < 2:
                    continue
                close = float(klines[0][4])
                open_ = float(klines[-1][1])
                if open_ <= 0:
                    continue
                pct = (close - open_) / open_ * 100
                if pct >= min_pct:
                    t = await self.ticker(symbol)
                    vol = t["volume_24h"] if t else 0
                    if vol < 100_000:
                        continue
                    return {
                        "symbol":     symbol,
                        "pct_change": pct,
                        "price":      close,
                        "timeframe":  tf["label"],
                        "volume_24h": vol,
                    }
            except Exception as e:
                logger.debug(f"check_pump {symbol}: {e}")
        return None

    async def scan(self):
        cfg = db_ref[0].get_settings()   # injected below
        target = cfg["target_pct"]
        results = []

        # Update watchlist prices
        for symbol in self.db.get_watchlist():
            try:
                t = await self.ticker(symbol)
                if not t:
                    continue
                self.db.update_watchlist_price(symbol, t["last_price"])
                info = self.db.get_coin_info(symbol)
                if not info:
                    continue
                pct = info["pct_current"]
                to_target = target - pct
                if pct >= target and not info["alerted_target"]:
                    self.db.mark_target_alerted(symbol)
                    results.append({"type": "target_reached", "symbol": symbol,
                                    "pct_total": pct, "price": t["last_price"]})
                elif 0 < to_target <= 10 and not info["alerted_near"]:
                    self.db.mark_near_alerted(symbol)
                    results.append({"type": "update", "symbol": symbol,
                                    "pct_total": pct, "price": t["last_price"],
                                    "to_target": to_target})
            except Exception as e:
                logger.error(f"watchlist update {symbol}: {e}")

        # Scan all symbols
        symbols = await self.all_symbols()
        wl = set(self.db.get_watchlist())
        logger.info(f"Scanning {len(symbols)} symbols...")

        batch = 25
        for i in range(0, len(symbols), batch):
            chunk = [s for s in symbols[i:i+batch] if s not in wl]
            tasks = [self.check_pump(s, cfg) for s in chunk]
            outs = await asyncio.gather(*tasks, return_exceptions=True)
            for alert in outs:
                if not alert or isinstance(alert, Exception):
                    continue
                self.db.add_to_watchlist(alert["symbol"], alert["price"],
                                         alert["pct_change"], alert["timeframe"])
                self.db.increment_found()
                wl.add(alert["symbol"])
                results.append({"type": "new_pump", **alert})
            await asyncio.sleep(0.2)

        logger.info(f"Scan done. {len(results)} events.")
        return results


# This will be set by bot.py after both objects are created
db_ref = [None]
