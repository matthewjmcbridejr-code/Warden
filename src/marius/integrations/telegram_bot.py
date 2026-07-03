"""
Marius Telegram Bot - Operator Interface v3.
"""
import os
import logging
import json
import asyncio
import httpx
from typing import List, Optional

try:
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        filters,
        ContextTypes,
    )
    TELEGRAM_INSTALLED = True
except ImportError:
    TELEGRAM_INSTALLED = False

# Configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_IDS_STR = os.getenv("MARIUS_TELEGRAM_ALLOWED_CHAT_IDS", "")
try:
    ALLOWED_IDS = [int(i.strip()) for i in ALLOWED_IDS_STR.split(",") if i.strip()]
except (ValueError, AttributeError):
    ALLOWED_IDS = []

API_BASE = os.getenv("MARIUS_API_BASE", "http://127.0.0.1:6969/api/mcharness/marius")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def check_env():
    errors = []
    if not TELEGRAM_INSTALLED:
        errors.append("python-telegram-bot is not installed. Run: .venv/bin/python -m pip install python-telegram-bot")
    if not TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN environment variable is missing.")
    if not ALLOWED_IDS:
        errors.append("MARIUS_TELEGRAM_ALLOWED_CHAT_IDS environment variable is missing or invalid.")
    return errors

def is_allowed(update) -> bool:
    if not update.effective_chat:
        return False
    return update.effective_chat.id in ALLOWED_IDS

async def api_request(method: str, endpoint: str, data: dict = None, params: dict = None, timeout: int = 180):
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "POST":
                resp = await client.post(url, json=data)
            else:
                resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.error(f"API Request failed: {e}")
    return None

async def auth_check(update, context) -> bool:
    if not is_allowed(update):
        logger.warning(f"Unauthorized access attempt from chat_id {update.effective_chat.id}")
        await update.message.reply_text("Unauthorized.")
        return False
    return True

async def start_cmd(update, context):
    if not await auth_check(update, context): return
    await update.message.reply_text("Marius Telegram Bridge Online. Safe local mode.")

async def status_cmd(update, context):
    if not await auth_check(update, context): return
    res = await api_request("GET", "status", timeout=5)
    if res:
        msg = f"Marius API Online.\nLoad: {res.get('load')}"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Marius API Offline.")

async def model_cmd(update, context):
    if not await auth_check(update, context): return
    res = await api_request("GET", "models", timeout=5)
    if res:
        msg = f"Profile: {res.get('current_profile')}\nModel: {res.get('forced_model') or 'Auto'}"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Marius API Offline.")

async def brain_cmd(update, context):
    if not await auth_check(update, context): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /brain <query>")
        return
    
    await update.message.reply_text("🧠 thinking...")
    res = await api_request("POST", "chat", data={"message": query, "brain_context": True})
    if res:
        reply = res.get("response", "No response")
        elapsed = res.get("elapsed", "?")
        await update.message.reply_text(f"{reply}\n[{elapsed}s]")
    else:
        await update.message.reply_text("Error.")

async def deep_cmd(update, context):
    if not await auth_check(update, context): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /deep <query>")
        return
        
    await update.message.reply_text("🌊 deep thinking...")
    
    # Save original profile
    models_res = await api_request("GET", "models", timeout=5)
    orig_prof = models_res.get("current_profile", "fast") if models_res else "fast"
    
    # Set deep
    await api_request("POST", "model/profile", data={"profile": "deep"}, timeout=5)
    
    res = await api_request("POST", "chat", data={"message": query, "brain_context": True})
    
    # Restore
    await api_request("POST", "model/profile", data={"profile": orig_prof}, timeout=5)

    if res:
        reply = res.get("response", "No response")
        elapsed = res.get("elapsed", "?")
        await update.message.reply_text(f"{reply}\n[{elapsed}s]")
    else:
        await update.message.reply_text("Error.")

async def recall_cmd(update, context):
    if not await auth_check(update, context): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /recall <query>")
        return
    res = await api_request("POST", "search/query", data={"query": query, "limit": 3}, timeout=10)
    if res and res.get("results"):
        out = ""
        for r in res["results"]:
            out += f"- [{r['project']}] {r['title']}\n"
        await update.message.reply_text(out)
    else:
        await update.message.reply_text("No records found or API offline.")

async def context_cmd(update, context):
    if not await auth_check(update, context): return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /context <query>")
        return
    res = await api_request("GET", "brain/context", params={"q": query}, timeout=10)
    if res and res.get("data"):
        await update.message.reply_text(res["data"].get("context_text", "Empty context"))
    else:
        await update.message.reply_text("Error.")

async def save_cmd(update, context):
    if not await auth_check(update, context): return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /save <text>")
        return
    
    res = await api_request("POST", "brain/ingest/text", data={"text": text, "title": "Telegram Note", "project": "personal", "tags": ["telegram"]})
    if res and res.get("ok"):
        await update.message.reply_text("Saved to brain.")
    else:
        await update.message.reply_text("Failed to save.")

async def handle_message(update, context):
    if not await auth_check(update, context): return
    text = update.message.text
    if not text: return
    
    # Casual chat, no brain by default
    res = await api_request("POST", "chat", data={"message": text, "brain_context": False})
    if res:
        reply = res.get("response", "No response")
        elapsed = res.get("elapsed", "?")
        await update.message.reply_text(f"{reply}\n[{elapsed}s]")
    else:
        await update.message.reply_text("Error connecting to local API.")

def doctor():
    print("Marius Telegram Bridge Doctor")
    print("-----------------------------")
    errors = check_env()
    if errors:
        for e in errors:
            print(f"FAILED: {e}")
        print("\nFix errors before starting.")
    else:
        print("OK: Token is present (hidden).")
        print(f"OK: Allowed IDs: {ALLOWED_IDS}")
        print("OK: Ready to start.")

def main():
    errors = check_env()
    if errors:
        for e in errors:
            logger.error(e)
        return

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("model", model_cmd))
    application.add_handler(CommandHandler("brain", brain_cmd))
    application.add_handler(CommandHandler("deep", deep_cmd))
    application.add_handler(CommandHandler("recall", recall_cmd))
    application.add_handler(CommandHandler("context", context_cmd))
    application.add_handler(CommandHandler("save", save_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Marius Telegram Bridge...")
    application.run_polling()

if __name__ == '__main__':
    main()
