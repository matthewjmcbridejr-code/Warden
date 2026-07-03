import sqlite3
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

MCHARNESS_DATA_ROOT = os.getenv("MCHARNESS_DATA_ROOT", "_mctable")
MARIUS_DATA_ROOT = os.getenv("MARIUS_DATA_ROOT", MCHARNESS_DATA_ROOT)
MEMORY_ROOT = Path(MARIUS_DATA_ROOT) / "marius" / "memory"

DB_PATH = MEMORY_ROOT / "marius_memory.db"
NOTES_DIR = MEMORY_ROOT / "notes"

def _ensure_paths():
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

def init_db():
    _ensure_paths()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_fact(content: str, category: str = "general"):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO facts (content, category) VALUES (?, ?)", (content, category))
    conn.commit()
    conn.close()
    
    # Also save to a markdown file for human readability
    date_str = datetime.now().strftime("%Y-%m-%d")
    with open(NOTES_DIR / f"{date_str}.md", "a") as f:
        f.write(f"- [{category}] {content} (at {datetime.now().strftime('%H:%M:%S')})\n")

def recall_facts(query: str) -> List[Dict[str, Any]]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT content, category, created_at FROM facts WHERE content LIKE ? OR category LIKE ? ORDER BY created_at DESC", (f"%{query}%", f"%{query}%"))
    results = cursor.fetchall()
    conn.close()
    return [{"content": r[0], "category": r[1], "created_at": r[2]} for r in results]

def set_where_left_off(summary: str):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO state (key, value, updated_at) VALUES ('where_left_off', ?, CURRENT_TIMESTAMP)", (summary,))
    conn.commit()
    conn.close()

def get_where_left_off() -> str:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM state WHERE key = 'where_left_off'")
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return "No recent progress recorded."

def get_recent_summaries() -> List[Dict[str, str]]:
    summaries = []
    if NOTES_DIR.exists():
        for file in sorted(NOTES_DIR.glob("*.md"), reverse=True)[:5]:
            with open(file, "r") as f:
                summaries.append({"date": file.stem, "content": f.read()})
    return summaries

init_db()
