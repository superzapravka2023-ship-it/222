import asyncio
import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from bybit_scanner import BybitScanner
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

db = Database()
scanner = BybitScanner(db)

# ─── KEYBOARDS ───────────────────────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Watchlist", callback_data="watchlist"),
            InlineKeyboardButton("📈 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh"),
        ],
        [
            InlineKeyboardButton("❓ Помощь", callback_data="help"),
        ]
    ])

def watchlist_keyboard(symbols):
    buttons = []
    for s in symbols:
        pnl = db.get_pnl(s)
        label = f"{'🟢' if pnl >= 0 else '🔴'} {s} ({pnl:+.1f}%)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"coin_{s}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def coin_keyboard(symbol):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Удалить из watchlist", callback_data=f"remove_{symbol}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="watchlist")],
    ])

def settings_keyboard():
    cfg = db.get_settings()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱ Мин. таймфрейм: {cfg['min_tf']}ч", callback_data="set_min_tf")],
        [InlineKeyboardButton(f"⏱ Макс. таймфрейм: {cfg['max_tf']}ч", callback_data="set_max_tf")],
        [InlineKeyboardButton(f"🚀 Мин. рост: {cfg['min_pct']}%", callback_data="set_min_pct")],
        [InlineKeyboardButton(f"🎯 Цель шорта: {cfg['target_pct']}%", callback_data="set_target_pct")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ])

# ─── COMMAND HANDLERS ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = db.get_settings()
    text = (
        "🤖 *Bybit Short Hunter*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Я мониторю фьючерсы Bybit и нахожу монеты,\n"
        "которые резко выросли — кандидаты для *шорта*.\n\n"
        f"📡 Сканирую каждые *5 минут*\n"
        f"📈 Рост за {cfg['min_tf']}–{cfg['max_tf']}ч: от *{cfg['min_pct']}%*\n"
        f"🎯 Цель для шорта: *{cfg['target_pct']}%*\n\n"
        "Выбери действие:"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "back_main" or data == "refresh":
        cfg = db.get_settings()
        wl = db.get_watchlist()
        text = (
            "🤖 *Bybit Short Hunter*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 Сканирую каждые *5 минут*\n"
            f"📈 Рост за {cfg['min_tf']}–{cfg['max_tf']}ч: от *{cfg['min_pct']}%*\n"
            f"🎯 Цель для шорта: *{cfg['target_pct']}%*\n"
            f"👁 В наблюдении: *{len(wl)} монет*\n\n"
            "Выбери действие:"
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    elif data == "watchlist":
        wl = db.get_watchlist()
        if not wl:
            text = "👁 *Watchlist пуст*\n\nБот автоматически добавит монеты при обнаружении."
            await q.edit_message_text(text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))
        else:
            text = "👁 *Watchlist — монеты под наблюдением:*\n\nНажми на монету для подробностей."
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=watchlist_keyboard(wl))

    elif data.startswith("coin_"):
        symbol = data[5:]
        info = db.get_coin_info(symbol)
        if info:
            text = (
                f"📌 *{symbol}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔍 Обнаружен: `{info['detected_at']}`\n"
                f"💰 Цена при обнаружении: `${info['price_detected']:.6f}`\n"
                f"💰 Текущая цена: `${info['price_current']:.6f}`\n"
                f"📈 Рост при обнаружении: `+{info['pct_at_detection']:.1f}%`\n"
                f"📊 Текущий рост: `{info['pct_current']:+.1f}%`\n"
                f"⏱ Таймфрейм: `{info['timeframe']}`\n\n"
                f"{'🎯 *Цель достигнута — готов к шорту!*' if info['pct_current'] >= db.get_settings()['target_pct'] else '⏳ Ждём достижения цели...'}"
            )
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=coin_keyboard(symbol))

    elif data.startswith("remove_"):
        symbol = data[7:]
        db.remove_from_watchlist(symbol)
        await q.answer(f"✅ {symbol} удалён из watchlist", show_alert=True)
        wl = db.get_watchlist()
        if not wl:
            await q.edit_message_text("👁 *Watchlist пуст*", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))
        else:
            await q.edit_message_text("👁 *Watchlist:*", parse_mode="Markdown", reply_markup=watchlist_keyboard(wl))

    elif data == "stats":
        stats = db.get_stats()
        text = (
            "📈 *Статистика бота*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Всего обнаружено: *{stats['total_found']}*\n"
            f"👁 Сейчас в watchlist: *{stats['in_watchlist']}*\n"
            f"🎯 Достигли цели: *{stats['reached_target']}*\n"
            f"📡 Последнее сканирование:\n`{stats['last_scan']}`\n\n"
            f"⏱ Работаю с: `{stats['started']}`"
        )
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))

    elif data == "settings":
        text = "⚙️ *Настройки сканера*\n\nНажми на параметр чтобы изменить:"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())

    elif data.startswith("set_"):
        param = data[4:]
        prompts = {
            "min_tf": "Введи минимальный таймфрейм в часах (1–24):\n/set min_tf <число>",
            "max_tf": "Введи максимальный таймфрейм в часах (1–36):\n/set max_tf <число>",
            "min_pct": "Введи минимальный % роста для алерта (10–100):\n/set min_pct <число>",
            "target_pct": "Введи целевой % роста для шорта (50–200):\n/set target_pct <число>",
        }
        await q.answer(prompts.get(param, ""), show_alert=True)

    elif data == "help":
        text = (
            "❓ *Как работает бот*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Каждые 5 минут сканирую ВСЕ USDT-фьючерсы Bybit\n\n"
            "2️⃣ Нахожу монеты, которые выросли на *50%+* за 1–36 часов\n\n"
            "3️⃣ Добавляю в *Watchlist* и слежу дальше\n\n"
            "4️⃣ Когда монета достигает цели *80–90%* — шлю алерт 🎯\n\n"
            "5️⃣ Это сигнал для входа в *ШОРТ* 📉\n\n"
            "*Команды:*\n"
            "/start — главное меню\n"
            "/set min\\_tf 1 — мин. таймфрейм (ч)\n"
            "/set max\\_tf 36 — макс. таймфрейм (ч)\n"
            "/set min\\_pct 50 — мин. % роста\n"
            "/set target\\_pct 80 — цель шорта (%)\n"
        )
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]]))

async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ Формат: /set <param> <value>\nПример: /set min_pct 50")
        return
    param, val = args[0], args[1]
    try:
        val = float(val)
        db.update_setting(param, val)
        await update.message.reply_text(f"✅ Параметр *{param}* обновлён: `{val}`",
            parse_mode="Markdown", reply_markup=main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ─── ALERT SENDER ────────────────────────────────────────────────────────────

async def send_alert(app, alert_type: str, data: dict):
    """Send beautiful alert to Telegram"""
    if alert_type == "new_pump":
        text = (
            f"🚨 *НАСОС ОБНАРУЖЕН!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 *{data['symbol']}*\n\n"
            f"📈 Рост: *+{data['pct_change']:.1f}%*\n"
            f"⏱ За: *{data['timeframe']}*\n"
            f"💰 Текущая цена: `${data['price']:.6f}`\n"
            f"💵 Объём 24ч: `${data['volume_24h']:,.0f}`\n\n"
            f"👁 Добавлена в *Watchlist*\n"
            f"⏳ Слежу до достижения цели..."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 Смотреть {data['symbol']}", callback_data=f"coin_{data['symbol']}")],
            [InlineKeyboardButton("👁 Весь Watchlist", callback_data="watchlist")],
        ])

    elif alert_type == "target_reached":
        text = (
            f"🎯 *ЦЕЛЬ ДОСТИГНУТА — ШОРТ!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪙 *{data['symbol']}*\n\n"
            f"📈 Итоговый рост: *+{data['pct_total']:.1f}%*\n"
            f"💰 Цена входа (шорт): `${data['price']:.6f}`\n"
            f"📉 Рекомендую: *ОТКРЫТЬ ШОРТ*\n\n"
            f"⚠️ _Не является финансовым советом.\nТоргуй на свой страх и риск._"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {data['symbol']} детали", callback_data=f"coin_{data['symbol']}")],
            [InlineKeyboardButton("🗑 Убрать из watchlist", callback_data=f"remove_{data['symbol']}")],
        ])

    elif alert_type == "update":
        text = (
            f"📡 *Обновление по {data['symbol']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 Рост с обнаружения: *+{data['pct_total']:.1f}%*\n"
            f"💰 Цена: `${data['price']:.6f}`\n"
            f"🎯 До цели: *{data['to_target']:.1f}%*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📊 {data['symbol']}", callback_data=f"coin_{data['symbol']}")],
        ])

    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")

# ─── SCANNER LOOP ─────────────────────────────────────────────────────────────

async def scanner_loop(app):
    """Main scanning loop - runs every 5 minutes"""
    await asyncio.sleep(5)  # small startup delay
    logger.info("🔍 Scanner started")

    # Send startup message
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                "✅ *Bybit Short Hunter запущен!*\n\n"
                "🔍 Начинаю мониторинг фьючерсов...\n"
                "📡 Сканирование каждые 5 минут"
            ),
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"Startup message failed: {e}")

    while True:
        try:
            logger.info("Running scan...")
            results = await scanner.scan()
            db.update_last_scan()

            for r in results:
                if r['type'] == 'new_pump':
                    await send_alert(app, 'new_pump', r)
                elif r['type'] == 'target_reached':
                    await send_alert(app, 'target_reached', r)
                elif r['type'] == 'update':
                    await send_alert(app, 'update', r)

        except Exception as e:
            logger.error(f"Scanner error: {e}")

        await asyncio.sleep(300)  # 5 minutes

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN env var not set")
    if not TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID env var not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Start scanner in background
    loop = asyncio.get_event_loop()

    async def run():
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            await scanner_loop(app)

    loop.run_until_complete(run())

if __name__ == "__main__":
    main()
