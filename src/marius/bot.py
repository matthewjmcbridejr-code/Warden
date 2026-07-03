import os
import requests
import time
import threading
from typing import Dict, Any, List

# Avoid circular imports by importing inside functions or using local imports
from . import router
from . import memory
from . import projects
from . import tools

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None

def send_message(chat_id: int, text: str):
    if not API_URL:
        return
    try:
        requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print(f"Failed to send telegram message: {e}")

def handle_update(update: Dict[str, Any]):
    if "message" not in update:
        return
    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    
    if not text:
        return

    if text.startswith("/status"):
        status = tools.get_system_status()
        svc_status = "\n".join([f"- {s['service']}: {s['status']}" for s in status['services']])
        msg = f"System Status:\nGit: {status['git']}\nLoad: {status['load']}\nServices:\n{svc_status}"
        send_message(chat_id, msg)
        
    elif text.startswith("/projects"):
        projs = projects.get_projects()
        p_list = "\n".join([f"- {p.name}: {p.description}" for p in projs])
        send_message(chat_id, f"Project Cards:\n{p_list}")
        
    elif text.startswith("/remember"):
        content = text.replace("/remember", "").strip()
        if content:
            memory.save_fact(content)
            if any(k in content.lower() for k in ["progress", "status", "leftoff"]):
                memory.set_where_left_off(content)
            send_message(chat_id, "Memory saved.")
        else:
            send_message(chat_id, "Usage: /remember <fact to save>")
            
    elif text.startswith("/recall"):
        query = text.replace("/recall", "").strip()
        results = memory.recall_facts(query)
        if results:
            r_list = "\n".join([f"- {r['content']} ({r['created_at']})" for r in results[:5]])
            send_message(chat_id, f"Recall Results:\n{r_list}")
        else:
            send_message(chat_id, "No matching memories found.")
            
    elif text.startswith("/whereleftoff"):
        summary = memory.get_where_left_off()
        send_message(chat_id, f"Where you left off:\n{summary}")
        
    elif text.startswith("/handoff"):
        parts = text.split()
        target = parts[1] if len(parts) > 1 else "generic"
        # In a real scenario, we might want to pass more context
        context = memory.get_where_left_off()
        prompt = router.create_handoff_prompt(target, context)
        send_message(chat_id, prompt)
        
    elif text.startswith("/help"):
        help_text = (
            "Marius Commands:\n"
            "/status - Server & Project health\n"
            "/projects - List active project cards\n"
            "/remember <note> - Save a durable fact\n"
            "/recall <query> - Search memory\n"
            "/whereleftoff - Get last recorded progress\n"
            "/handoff [agent] - Generate handoff prompt\n"
            "/help - Show this help"
        )
        send_message(chat_id, help_text)
        
    elif text.startswith("/"):
        send_message(chat_id, "Unknown command. Use /help for available commands.")
        
    else:
        # Default to chat completion
        response, provider = router.chat_completion(text)
        send_message(chat_id, response)

def _poll_loop():
    last_update_id = 0
    print("Telegram bot polling started...")
    while True:
        try:
            resp = requests.get(
                f"{API_URL}/getUpdates", 
                params={"offset": last_update_id + 1, "timeout": 20},
                timeout=25
            )
            if resp.status_code == 200:
                updates = resp.json().get("result", [])
                for update in updates:
                    handle_update(update)
                    last_update_id = update["update_id"]
            elif resp.status_code == 401:
                print("Telegram Bot Token is invalid (401). Stopping poll.")
                break
        except Exception as e:
            # Silence expected errors in some environments, but log for debug
            time.sleep(10)

def start_bot():
    if os.getenv("MARIUS_TELEGRAM_ENABLED") != "1":
        print("MARIUS_TELEGRAM_ENABLED not set to 1, Telegram bot disabled by default.")
        return None
        
    if not API_URL:
        print("TELEGRAM_BOT_TOKEN not set, Telegram bot will not start.")
        return None
    
    try:
        thread = threading.Thread(target=_poll_loop, daemon=True)
        thread.start()
        return thread
    except Exception as e:
        print(f"Failed to start Marius Telegram bot: {e}")
        return None
