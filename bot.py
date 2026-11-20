"""
Bybit Short Hunter Bot
Pure aiohttp + raw Telegram API — zero dependency on python-telegram-bot.
Works on Python 3.8 → 3.14+
"""
import asyncio
import logging
import os

from telegram_api import TelegramAPI, inline_keyboard
from database import Database
from bybit_scanner import BybitScanner, db_ref

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN   = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

tg      = TelegramAPI(TOKEN)
db      = Database()
scanner = BybitScanner(db)
db_ref[0] = db   # give scanner access to db


# ─── KEYBOARDS ────────────────────────────────────────────────────────────────

def kb_main():
    return inline_keyboard(
        [("📊 Watchlist", "watchlist"),  ("📈 Статистика",  "stats")],
        [("⚙️ Настройки", "settings"),   ("🔄 Обновить",    "back_main")],
        [("❓ Помощь",    "help")],
    )

def kb_watchlist(symbols):
    rows = []
    for s in symbols:
        pnl = db.get_pnl(s)
        em  = "🟢" if pnl >= 0 else "🔴"
        rows.append([(f"{em} {s} ({pnl:+.1f}%)", f"coin_{s}")])
    rows.append([("🔙 Назад", "back_main")])
    return inline_keyboard(*rows)

def kb_coin(symbol):
    return inline_keyboard(
        [(f"🗑 Удалить из watchlist", f"remove_{symbol}")],
        [("🔙 Назад", "watchlist")],
    )

def kb_settings():
    cfg = db.get_settings()
    return inline_keyboard(
        [(f"⏱ Мин. таймфрейм: {int(cfg['min_tf'])}ч",  "set_min_tf")],
        [(f"⏱ Макс. таймфрейм: {int(cfg['max_tf'])}ч", "set_max_tf")],
        [(f"🚀 Мин. рост: {int(cfg['min_pct'])}%",      "set_min_pct")],
        [(f"🎯 Цель шорта: {int(cfg['target_pct'])}%",  "set_target_pct")],
        [("🔙 Назад", "back_main")],
    )

def kb_back(to="back_main"):
    return inline_keyboard([("🔙 Назад", to)])


# ─── TEXT BUILDERS ────────────────────────────────────────────────────────────

def text_main():
    cfg = db.get_settings()
    wl  = db.get_watchlist()
    return (
        "🤖 *Bybit Short Hunter*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Мониторю фьючерсы Bybit и нахожу монеты,\n"
        "которые резко выросли — кандидаты для *шорта*.\n\n"
        f"📡 Сканирую каждые *5 минут*\n"
        f"📈 Рост за {int(cfg['min_tf'])}–{int(cfg['max_tf'])}ч: от *{int(cfg['min_pct'])}%*\n"
        f"🎯 Цель для шорта: *{int(cfg['target_pct'])}%*\n"
        f"👁 В наблюдении: *{len(wl)} монет*\n\n"
        "Выбери действие:"
    )


# ─── COMMAND HANDLERS ─────────────────────────────────────────────────────────

async def handle_message(msg: dict):
    text    = msg.get("text", "").strip()
    chat_id = msg["chat"]["id"]

    if text == "/start":
        await tg.send_message(chat_id, text_main(), reply_markup=kb_main())

    elif text.startswith("/set "):
        parts = text.split()
        valid = {"min_tf", "max_tf", "min_pct", "target_pct"}
        if len(parts) == 3 and parts[1] in valid:
            try:
                db.update_setting(parts[1], float(parts[2]))
                await tg.send_message(
                    chat_id,
                    f"✅ *{parts[1]}* обновлён: `{parts[2]}`",
                    reply_markup=kb_main()
                )
            except Exception as e:
                await tg.send_message(chat_id, f"❌ Ошибка: {e}")
        else:
            await tg.send_message(
                chat_id,
                "❌ Формат: `/set <param> <value>`\n"
                f"Параметры: {', '.join(valid)}"
            )


# ─── CALLBACK HANDLERS ────────────────────────────────────────────────────────

async def handle_callback(cq: dict):
    cq_id  = cq["id"]
    data   = cq.get("data", "")
    chat   = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    cfg    = db.get_settings()

    async def edit(text, kb=None):
        await tg.edit_message_text(chat, msg_id, text, reply_markup=kb)

    await tg.answer_callback_query(cq_id)

    if data == "back_main":
        await edit(text_main(), kb_main())

    elif data == "watchlist":
        wl = db.get_watchlist()
        if not wl:
            await edit("👁 *Watchlist пуст*\n\nБот добавит монеты автоматически.", kb_back())
        else:
            await edit("👁 *Watchlist — монеты под наблюдением:*", kb_watchlist(wl))

    elif data.startswith("coin_"):
        symbol = data[5:]
        info = db.get_coin_info(symbol)
        if info:
            at_target = info["pct_current"] >= cfg["target_pct"]
            await edit(
                f"📌 *{symbol}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔍 Обнаружен: `{info['detected_at']}`\n"
                f"💰 Цена при обнаружении: `${info['price_detected']:.6f}`\n"
                f"💰 Текущая цена: `${info['price_current']:.6f}`\n"
                f"📈 Рост при обнаружении: `+{info['pct_at_detection']:.1f}%`\n"
                f"📊 Текущий рост: `{info['pct_current']:+.1f}%`\n"
                f"⏱ Таймфрейм: `{info['timeframe']}`\n\n"
                + ("🎯 *Цель достигнута — готов к шорту!*"
                   if at_target else "⏳ Ждём достижения цели..."),
                kb_coin(symbol),
            )
        else:
            await edit("❌ Монета не найдена.", kb_back("watchlist"))

    elif data.startswith("remove_"):
        symbol = data[7:]
        db.remove_from_watchlist(symbol)
        await tg.answer_callback_query(cq_id, f"✅ {symbol} удалён", show_alert=True)
        wl = db.get_watchlist()
        if wl:
            await edit("👁 *Watchlist:*", kb_watchlist(wl))
        else:
            await edit("👁 *Watchlist пуст*", kb_back())

    elif data == "stats":
        s = db.get_stats()
        await edit(
            "📈 *Статистика бота*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Всего обнаружено: *{s['total_found']}*\n"
            f"👁 Сейчас в watchlist: *{s['in_watchlist']}*\n"
            f"🎯 Достигли цели: *{s['reached_target']}*\n"
            f"📡 Последнее сканирование:\n`{s['last_scan']}`\n\n"
            f"⏱ Работаю с: `{s['started']}`",
            kb_back(),
        )

    elif data == "settings":
        await edit(
            "⚙️ *Настройки сканера*\n\n"
            "Нажми кнопку — получи подсказку команды для изменения:",
            kb_settings(),
        )

    elif data.startswith("set_"):
        hints = {
            "set_min_tf":     "Введи в чат:\n/set min_tf 1",
            "set_max_tf":     "Введи в чат:\n/set max_tf 36",
            "set_min_pct":    "Введи в чат:\n/set min_pct 50",
            "set_target_pct": "Введи в чат:\n/set target_pct 80",
        }
        await tg.answer_callback_query(cq_id, hints.get(data, ""), show_alert=True)

    elif data == "help":
        await edit(
            "❓ *Как работает бот*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Каждые 5 минут сканирую ВСЕ USDT-фьючерсы Bybit\n\n"
            "2️⃣ Нахожу монеты с ростом *50%+* за 1–36 часов\n\n"
            "3️⃣ Добавляю в *Watchlist* и слежу дальше\n\n"
            "4️⃣ Когда монета достигает *80%+* — алерт 🎯\n\n"
            "5️⃣ Это сигнал для входа в *ШОРТ* 📉\n\n"
            "*Команды:*\n"
            "`/start` — главное меню\n"
            "`/set min_tf 1` — мин. таймфрейм (ч)\n"
            "`/set max_tf 36` — макс. таймфрейм (ч)\n"
            "`/set min_pct 50` — мин. % роста\n"
            "`/set target_pct 80` — цель шорта (%)\n",
            kb_back(),
        )


# ─── ALERT SENDER ─────────────────────────────────────────────────────────────

async def send_alert(alert_type: str, data: dict):
    if alert_type == "new_pump":
        text = (
            f"🚨 *НАСОС ОБНАРУЖЕН!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 *{data['symbol']}*\n\n"
            f"📈 Рост: *+{data['pct_change']:.1f}%*\n"
            f"⏱ За: *{data['timeframe']}*\n"
            f"💰 Цена: `${data['price']:.6f}`\n"
            f"💵 Объём 24ч: `${data['volume_24h']:,.0f}`\n\n"
            f"👁 Добавлена в *Watchlist* — слежу за ростом..."
        )
        kb = inline_keyboard(
            [(f"📊 {data['symbol']}", f"coin_{data['symbol']}")],
            [("👁 Watchlist",          "watchlist")],
        )

    elif alert_type == "target_reached":
        text = (
            f"🎯 *ЦЕЛЬ ДОСТИГНУТА — ШОРТ!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 *{data['symbol']}*\n\n"
            f"📈 Итоговый рост: *+{data['pct_total']:.1f}%*\n"
            f"💰 Цена входа (шорт): `${data['price']:.6f}`\n\n"
            f"📉 *ОТКРЫВАЙ ШОРТ!*\n\n"
            f"⚠️ _Не является финансовым советом_"
        )
        kb = inline_keyboard(
            [(f"📊 {data['symbol']} детали", f"coin_{data['symbol']}")],
            [(f"🗑 Убрать из watchlist",      f"remove_{data['symbol']}")],
        )

    elif alert_type == "update":
        text = (
            f"📡 *Близко к цели: {data['symbol']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 Рост: *+{data['pct_total']:.1f}%*\n"
            f"💰 Цена: `${data['price']:.6f}`\n"
            f"🎯 До цели: *{data['to_target']:.1f}%*"
        )
        kb = inline_keyboard([(f"📊 {data['symbol']}", f"coin_{data['symbol']}")])

    else:
        return

    await tg.send_message(CHAT_ID, text, reply_markup=kb)


# ─── POLLING LOOP ─────────────────────────────────────────────────────────────

async def polling_loop():
    logger.info("Polling loop started")
    while True:
        try:
            updates = await tg.get_updates(timeout=25)
            for upd in updates:
                if "message" in upd:
                    await handle_message(upd["message"])
                elif "callback_query" in upd:
                    await handle_callback(upd["callback_query"])
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(3)


# ─── SCANNER LOOP ─────────────────────────────────────────────────────────────

async def scanner_loop():
    await asyncio.sleep(3)
    logger.info("Scanner loop started")

    await tg.send_message(
        CHAT_ID,
        "✅ *Bybit Short Hunter запущен!*\n\n"
        "🔍 Начинаю мониторинг фьючерсов Bybit...\n"
        "📡 Первый скан через ~30 секунд\n"
        "⏱ Далее каждые 5 минут",
        reply_markup=kb_main(),
    )

    while True:
        try:
            logger.info("Running scan...")
            results = await scanner.scan()
            db.update_last_scan()
            for r in results:
                await send_alert(r["type"], r)
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Scanner error: {e}")
        await asyncio.sleep(300)   # 5 min


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

async def main():
    logger.info("Bybit Short Hunter starting...")
    await asyncio.gather(
        polling_loop(),
        scanner_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())
