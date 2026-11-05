import os, sys, csv, time, uuid, asyncio, datetime
import duckdb
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

sys.path.insert(0, "agent")
sys.path.insert(0, "bot")
from sql_agent import answer, DB
from chart import make_chart
from valuation import valuation_reply
import watch

DB_URL = os.environ["DB_URL"]
ALLOWED = {int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x}
FEEDBACK_LOG = "evals/feedback.csv"


# ---------- data download ----------

def refresh_db():
    tmp = DB + ".tmp"
    for attempt in range(3):
        try:
            with requests.get(DB_URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                expected = int(r.headers.get("Content-Length", 0))
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            if expected and os.path.getsize(tmp) != expected:
                raise IOError("Incomplete download")
            os.replace(tmp, DB)
            return
        except (requests.RequestException, IOError):
            if attempt == 2:
                raise
            time.sleep(3)

async def refresh_job(context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(refresh_db)
    # After new data arrives, tell watchers about new sales in their blocks
    for chat_id, message in await asyncio.to_thread(watch.check_new):
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:  # e.g. the user blocked the bot
            print(f"Could not send watch alert to {chat_id}: {e}")


# ---------- helpers ----------

def allowed(update: Update) -> bool:
    return not ALLOWED or update.effective_chat.id in ALLOWED

def query(sql, params=None):
    """Run a fixed, parameterised query (never user-written SQL)."""
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


# ---------- commands ----------

HELP_TEXT = (
    "Ask me about HDB resale prices in plain English. For example:\n"
    "• Median 4-room price in Bedok in 2025?\n"
    "• Which 5 towns had the highest median 5-room price psm last year?\n"
    "• How many resale transactions were there each year?\n\n"
    "Commands:\n"
    "/sql – show the SQL behind my last answer\n"
    "/comps <block> <flat type> – recent sales in a block, e.g. /comps 123 4 ROOM\n"
    "/valuation <flat details> – estimate a fair price, e.g.\n"
    "   /valuation 3 room, blk 406 Ang Mo Kio Ave 10, 10th floor, 67 sqm\n"
    "/watch <block> <street> <flat type> – get a message when new sales appear, e.g.\n"
    "   /watch 540 Ang Mo Kio Ave 10 3 room\n"
    "/watching – blocks you're watching · /unwatch <number> – stop one\n"
    "/data – what period the data covers\n"
    "/help – this message\n\n"
    "Tap 👍 or 👎 under an answer to tell me if it was right."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(HELP_TEXT)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(HELP_TEXT)

async def show_sql(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(context.chat_data.get("last_sql", "No query yet."))

async def data_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    first, last, n = query(
        "SELECT strftime(MIN(txn_month), '%b %Y'), strftime(MAX(txn_month), '%b %Y'), COUNT(*) "
        "FROM fct_resale")[0]
    refreshed = datetime.datetime.fromtimestamp(os.path.getmtime(DB)).strftime("%d %b %Y, %H:%M")
    await update.message.reply_text(
        f"Data covers HDB resale registrations from {first} to {last} ({n:,} transactions).\n"
        f"Last downloaded: {refreshed}.")

async def comps_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /comps <block> <flat type>\nExample: /comps 123 4 ROOM")
        return
    block = context.args[0].upper()
    flat_type = " ".join(context.args[1:]).upper()
    rows = query(
        """SELECT strftime(txn_month, '%b %Y'), town, street_name, storey_range,
                  floor_area_sqm, resale_price
           FROM fct_resale
           WHERE block = ? AND flat_type = ?
           ORDER BY txn_month DESC
           LIMIT 10""",
        [block, flat_type])
    if not rows:
        await update.message.reply_text(
            f"No {flat_type} sales found for block {block}. "
            "Check the flat type, e.g. 3 ROOM, 4 ROOM, 5 ROOM, EXECUTIVE.")
        return
    lines = [f"Latest {flat_type} sales at block {block}:"]
    for month, town, street, storey, area, price in rows:
        lines.append(f"• {month} · {town}, {street} · {storey} · {area:.0f} sqm · S${price:,.0f}")
    lines.append("\nThe same block number can exist in several towns, so check the street.")
    await update.message.reply_text("\n".join(lines))


async def valuation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text(
            "Tell me about the flat, e.g.\n"
            "/valuation 3 room, blk 406 Ang Mo Kio Ave 10, 10th floor, 67 sqm\n"
            "Block, street and flat type are needed; floor and size are optional.")
        return
    await update.message.chat.send_action("typing")
    reply = await asyncio.to_thread(valuation_reply, text)
    await update.message.reply_text(reply)


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        reply = await asyncio.to_thread(watch.add, update.effective_chat.id, " ".join(context.args))
        await update.message.reply_text(reply)

async def watching_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(watch.listing(update.effective_chat.id))

async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await update.message.reply_text(watch.remove(update.effective_chat.id, " ".join(context.args)))


# ---------- questions + feedback ----------

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.chat.send_action("typing")
    question = update.message.text
    text, sql, df = await asyncio.to_thread(answer, question)
    context.chat_data["last_sql"] = sql

    answer_id = uuid.uuid4().hex[:8]
    context.chat_data.setdefault("answers", {})[answer_id] = {"q": question, "sql": sql}
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"fb:up:{answer_id}"),
        InlineKeyboardButton("👎", callback_data=f"fb:down:{answer_id}"),
    ]])
    await update.message.reply_text(text, reply_markup=buttons)

    png = await asyncio.to_thread(make_chart, df, question)
    if png:
        await update.message.reply_photo(photo=png)

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, vote, answer_id = q.data.split(":")
    record = context.chat_data.get("answers", {}).get(answer_id)
    if record:
        is_new = not os.path.exists(FEEDBACK_LOG)
        os.makedirs(os.path.dirname(FEEDBACK_LOG), exist_ok=True)
        with open(FEEDBACK_LOG, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["timestamp", "vote", "question", "sql"])
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                        vote, record["q"], record["sql"]])
    await q.answer("Thanks, noted!")
    await q.edit_message_reply_markup(reply_markup=None)


# ---------- main ----------

def main():
    refresh_db()
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("sql", show_sql))
    app.add_handler(CommandHandler("data", data_cmd))
    app.add_handler(CommandHandler("comps", comps_cmd))
    app.add_handler(CommandHandler("valuation", valuation_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("watching", watching_cmd))
    app.add_handler(CommandHandler("unwatch", unwatch_cmd))
    app.add_handler(CallbackQueryHandler(feedback, pattern=r"^fb:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.job_queue.run_repeating(refresh_job, interval=86400, first=86400)
    app.run_polling()

if __name__ == "__main__":
    main()