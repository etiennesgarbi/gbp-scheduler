"""Gestione stato persistente dei post GBP via SQLite."""
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("state.db")

def _conn() -> sqlite3.Connection:
    """Apre connessione SQLite con row_factory."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    """Crea la tabella posts se non esiste."""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                post_id     TEXT PRIMARY KEY,
                csv_file    TEXT NOT NULL,
                location    TEXT NOT NULL,
                title       TEXT,
                status      TEXT NOT NULL DEFAULT 'pending',
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_error  TEXT,
                gbp_post_url TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)

def make_post_id(title: str, date: str, location: str) -> str:
    """Genera post_id deterministico: sha256(title+date+location)[:16]."""
    raw = f"{title}|{date}|{location}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def load_state(csv_file: str, location: str, posts: list[dict]) -> dict:
    """
    Carica lo stato esistente dal DB per la coppia csv_file+location.
    Inserisce le righe mancanti come 'pending'.
    Ritorna dict {post_id: Row}.
    """
    init_db()
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        for p in posts:
            pid = make_post_id(p.get("title",""), p.get("date",""), location)
            con.execute("""
                INSERT OR IGNORE INTO posts
                (post_id, csv_file, location, title, status, attempts, created_at, updated_at)
                VALUES (?,?,?,?,'pending',0,?,?)
            """, (pid, csv_file, location, p.get("title",""), now, now))
        rows = con.execute(
            "SELECT * FROM posts WHERE csv_file=? AND location=?",
            (csv_file, location)
        ).fetchall()
    return {r["post_id"]: dict(r) for r in rows}

def is_done(post_id: str) -> bool:
    """True se il post è già stato pubblicato con successo."""
    init_db()
    with _conn() as con:
        row = con.execute("SELECT status FROM posts WHERE post_id=?", (post_id,)).fetchone()
    return row is not None and row["status"] == "published"

def update_post(
    post_id: str,
    status: str,
    error: Optional[str] = None,
    gbp_post_url: Optional[str] = None
) -> None:
    """Aggiorna status, attempts, last_error, updated_at."""
    init_db()
    now = datetime.utcnow().isoformat()
    with _conn() as con:
        con.execute("""
            UPDATE posts
            SET status=?, attempts=attempts+1, last_error=?, gbp_post_url=?, updated_at=?
            WHERE post_id=?
        """, (status, error, gbp_post_url, now, post_id))
