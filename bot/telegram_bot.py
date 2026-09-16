import os
import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

from db.database import get_conn
from agent.orchestrator import run_turn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kirana-bot")


def _already_seen(update_id: int) -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT 1 FROM telegram_updates_seen WHERE update_id = ?", (update_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def _mark_seen(update_id: int, chat_id: str):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO telegram_updates_seen(update_id, chat_id) VALUES (?,?)", (update_id, chat_id)
        )
        conn.commit()
    finally:
        conn.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = str(update.effective_chat.id)
    update_id = update.update_id

    # Transport-level idempotency: Telegram can redeliver the same update
    # (e.g. after a slow reply or a restart). We record every update_id we've
    # started processing and skip repeats before they ever reach the agent.
    if _already_seen(update_id):
        log.info("Duplicate update %s for chat %s, skipping.", update_id, chat_id)
        return
    _mark_seen(update_id, chat_id)

    text = update.message.text.strip()
    await update.message.chat.send_action("typing")

    try:
        reply, files = run_turn(chat_id, update_id, text)
    except Exception:
        log.exception("Turn failed for chat %s", chat_id)
        await update.message.reply_text(
            "Something went wrong on my end handling that — nothing was changed. Try again?"
        )
        return

    await update.message.reply_text(reply)
    for path in files:
        try:
            with open(path, "rb") as f:
                await update.message.reply_document(f, filename=os.path.basename(path))
        except Exception:
            log.exception("Failed to send generated file %s", path)


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    conn = get_conn()
    try:
        conn.execute("DELETE FROM conversation_messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()
    await update.message.reply_text(
        "Fresh chat started. Conversation history is cleared, but everything the store knows — "
        "stock, khata, past bills, and your saved preferences — is unchanged."
    )


def build_app():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "new"], new_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def main():
    from db.database import init_db
    init_db()
    app = build_app()
    log.info("Bot starting (long polling)...")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
