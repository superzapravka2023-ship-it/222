import asyncio
import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from bybit_scanner import BybitScanner
from database import Database

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

db      = Database()
scanner = BybitScanner(db)

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Watchlist",   callback_data="watchlist"),
            InlineKeyboardButton("📈 Статистика",  callback_data="stats"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки",  callback_data="settings"),
            InlineKeyboardButton("🔄 Обновить",   callback_data="back_main"),
        ],
        [InlineKeyboardButton("❓ Помощь",         callback_data="help")],
    ])

def watchlist_keyboard(symbols):
    buttons = []
    for s in symbols:
        pnl   = db.get_pnl(s)
        emoji = "🟢" if pnl >= 0 else "🔴"
        label = f"{emoji} {s} ({pnl:+.1f}%)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"coin_{s}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def coin_keyboard(symbol):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить из watchlist", callback_data=f"remove_{symbol}")],
        [InlineKeyboardButton("🔙 Назад",                callback_data="watchlist")],
    ])

def settings_keyboard():
    cfg = db.get_settings()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ Мин. таймфрейм: {int(cfg['min_tf'])}ч",    callback_data="set_min_tf")],
        [InlineKeyboardButton(f"⏱ Макс. таймфрейм: {int(cfg['max_tf'])}ч",   callback_data="set_max_tf")],
        [InlineKeyboardButton(f"🚀 Мин. рост: {int(cfg['min_pct'])}%",        callback_data="set_min_pct")],
        [InlineKeyboardButton(f"🎯 Цель шорта: {int(cfg['target_pct'])}%",    callback_data="set_target_pct")],
        [InlineKeyboardButton("🔙 Назад",                                       callback_data="back_main")],
    ])

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = db.get_settings()
    wl  = db.get_watchlist()
    text = (
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
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    valid = {"min_tf", "max_tf", "min_pct", "target_pct"}
    if len(args) != 2 or args[0] not in valid:
        await update.message.reply_text(
            "❌ Формат: `/set <param> <value>`\n"
            f"Параметры: {', '.join(valid)}",
            parse_mode="Markdown"
        )
        return
    try:
        db.update_setting(args[0], float(args[1]))
        await update.message.reply_text(
            f"✅ *{args[0]}* = `{args[1]}`",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    cfg = db.get_settings()
    wl  = db.get_watchlist()

    # ── Main / refresh ───────────────────────────────────────────────────────
    if data == "back_main":
        text = (
            "🤖 *Bybit Short Hunter*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 Сканирую каждые *5 минут*\n"
            f"📈 Рост за {int(cfg['min_tf'])}–{int(cfg['max_tf'])}ч: от *{int(cfg['min_pct'])}%*\n"
            f"🎯 Цель для шорта: *{int(cfg['target_pct'])}%*\n"
            f"👁 В наблюдении: *{len(wl)} монет*\n\n"
            "Выбери действие:"
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    # ── Watchlist ─────────────────────────────────────────────────────────────
    elif data == "watchlist":
        if not wl:
            await q.edit_message_text(
                "👁 *Watchlist пуст*\n\nБот добавит монеты автоматически при обнаружении.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]),
            )
        else:
            await q.edit_message_text(
                "👁 *Watchlist — монеты под наблюдением:*",
                parse_mode="Markdown",
                reply_markup=watchlist_keyboard(wl),
            )

    # ── Coin detail ───────────────────────────────────────────────────────────
    elif data.startswith("coin_"):
        symbol = data[5:]
        info   = db.get_coin_info(symbol)
        if info:
            at_target = info["pct_current"] >= cfg["target_pct"]
            text = (
                f"📌 *{symbol}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔍 Обнаружен: `{info['detected_at']}`\n"
                f"💰 Цена при обнаружении: `${info['price_detected']:.6f}`\n"
                f"💰 Текущая цена: `${info['price_current']:.6f}`\n"
                f"📈 Рост при обнаружении: `+{info['pct_at_detection']:.1f}%`\n"
                f"📊 Текущий рост: `{info['pct_current']:+.1f}%`\n"
                f"⏱ Таймфрейм: `{info['timeframe']}`\n\n"
                + ("🎯 *Цель достигнута — готов к шорту!*" if at_target else "⏳ Ждём достижения цели...")
            )
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=coin_keyboard(symbol))
        else:
            await q.edit_message_text("❌ Монета не найдена в watchlist.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="watchlist")]]))

    # ── Remove ────────────────────────────────────────────────────────────────
    elif data.startswith("remove_"):
        symbol = data[7:]
        db.remove_from_watchlist(symbol)
        await q.answer(f"✅ {symbol} удалён", show_alert=True)
        wl = db.get_watchlist()
        if not wl:
            await q.edit_message_text("👁 *Watchlist пуст*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))
        else:
            await q.edit_message_text("👁 *Watchlist:*", parse_mode="Markdown",
                reply_markup=watchlist_keyboard(wl))

    # ── Stats ─────────────────────────────────────────────────────────────────
    elif data == "stats":
        s = db.get_stats()
        text = (
            "📈 *Статистика бота*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Всего обнаружено: *{s['total_found']}*\n"
            f"👁 Сейчас в watchlist: *{s['in_watchlist']}*\n"
            f"🎯 Достигли цели: *{s['reached_target']}*\n"
            f"📡 Последнее сканирование:\n`{s['last_scan']}`\n\n"
            f"⏱ Работаю с: `{s['started']}`"
        )
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))

    # ── Settings ──────────────────────────────────────────────────────────────
    elif data == "settings":
        await q.edit_message_text(
            "⚙️ *Настройки сканера*\n\nНажми на параметр, затем используй команду для изменения:",
            parse_mode="Markdown", reply_markup=settings_keyboard()
        )

    elif data.startswith("set_"):
        hints = {
            "set_min_tf":     "Введи: `/set min_tf <часы>`\nПример: `/set min_tf 1`",
            "set_max_tf":     "Введи: `/set max_tf <часы>`\nПример: `/set max_tf 36`",
            "set_min_pct":    "Введи: `/set min_pct <процент>`\nПример: `/set min_pct 50`",
            "set_target_pct": "Введи: `/set target_pct <процент>`\nПример: `/set target_pct 80`",
        }
        await q.answer(hints.get(data, ""), show_alert=True)

    # ── Help ──────────────────────────────────────────────────────────────────
    elif data == "help":
        text = (
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
            "`/set target_pct 80` — цель шорта (%)\n"
        )
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))

# ─── ALERT SENDER ─────────────────────────────────────────────────────────────

async def send_alert(app: Application, alert_type: str, data: dict):
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
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {data['symbol']}", callback_data=f"coin_{data['symbol']}")],
            [InlineKeyboardButton("👁 Watchlist",          callback_data="watchlist")],
        ])

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
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {data['symbol']} детали", callback_data=f"coin_{data['symbol']}")],
            [InlineKeyboardButton("🗑 Убрать из watchlist",       callback_data=f"remove_{data['symbol']}")],
        ])

    elif alert_type == "update":
        text = (
            f"📡 *Близко к цели: {data['symbol']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 Рост: *+{data['pct_total']:.1f}%*\n"
            f"💰 Цена: `${data['price']:.6f}`\n"
            f"🎯 До цели осталось: *{data['to_target']:.1f}%*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {data['symbol']}", callback_data=f"coin_{data['symbol']}")],
        ])
    else:
        return

    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"Alert send error: {e}")

# ─── SCANNER LOOP ─────────────────────────────────────────────────────────────

async def scanner_loop(app: Application):
    await asyncio.sleep(5)
    logger.info("Scanner started")
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                "✅ *Bybit Short Hunter запущен!*\n\n"
                "🔍 Начинаю мониторинг фьючерсов...\n"
                "📡 Сканирование каждые 5 минут\n\n"
                "Первый скан займёт ~2 минуты."
            ),
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        logger.error(f"Startup msg error: {e}")

    while True:
        try:
            logger.info("Running scan...")
            results = await scanner.scan()
            db.update_last_scan()
            for r in results:
                await send_alert(app, r["type"], r)
                await asyncio.sleep(0.5)   # small gap between alerts
        except Exception as e:
            logger.error(f"Scanner loop error: {e}")
        await asyncio.sleep(300)   # 5 minutes

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set",   set_cmd))
    app.add_handler(CallbackQueryHandler(button))

    # Schedule scanner as a job
    app.job_queue  # ensure job_queue is initialized

    async def post_init(application: Application):
        asyncio.create_task(scanner_loop(application))

    app.post_init = post_init

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
