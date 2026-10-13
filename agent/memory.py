"""Persistent memory (Milestone 4).

Two things are stored in one SQLite file (default: data/memory.db):

1. preferences  - things the agent has LEARNED from the human (e.g. 'Call Bob "Robert"').
                  They are loaded at the start of every run and injected into the prompts.
2. runs         - one row per processed email (thread_id, triage, status). The UI uses it
                  to show the inbox history and the emails WAITING for human approval.

The LangGraph checkpoints (needed for interrupt/resume) live in a separate SQLite file,
see agent/graph.py -> get_checkpointer().
"""
import json
import os
import sqlite3
import threading
from datetime import datetime

DEFAULT_DB = os.getenv("MEMORY_DB", "data/memory.db")


class MemoryStore:
    def __init__(self, path: str = DEFAULT_DB):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT NOT NULL,          -- 'response' or 'triage'
                text       TEXT NOT NULL,
                source     TEXT,                   -- 'hitl_edit', 'triage_correction', 'manual'
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                thread_id  TEXT PRIMARY KEY,
                email_json TEXT NOT NULL,
                triage     TEXT,
                status     TEXT,                   -- running / waiting_approval / done / denied / ignored / notified
                pending    TEXT,                   -- JSON of the action waiting for approval
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    # ---------------- preferences ----------------
    def add_preference(self, text: str, kind: str = "response", source: str = "manual") -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            exists = self.conn.execute(
                "SELECT 1 FROM preferences WHERE kind=? AND lower(text)=lower(?)", (kind, text)).fetchone()
            if not exists:
                self.conn.execute(
                    "INSERT INTO preferences(kind, text, source, created_at) VALUES (?,?,?,?)",
                    (kind, text, source, _now()))
                self.conn.commit()

    def get_preferences(self, kind: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM preferences", ()
        if kind:
            q, args = q + " WHERE kind=?", (kind,)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY id", args).fetchall()]

    def delete_preference(self, pref_id: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM preferences WHERE id=?", (pref_id,))
            self.conn.commit()

    def clear_preferences(self) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM preferences")
            self.conn.commit()

    # ---------------- runs ----------------
    def upsert_run(self, thread_id: str, email: dict, triage: str | None = None,
                   status: str | None = None, pending: dict | None = None) -> None:
        with self._lock:
            old = self.conn.execute("SELECT * FROM runs WHERE thread_id=?", (thread_id,)).fetchone()
            triage = triage if triage is not None else (old["triage"] if old else None)
            status = status if status is not None else (old["status"] if old else "running")
            self.conn.execute(
                "INSERT OR REPLACE INTO runs(thread_id, email_json, triage, status, pending, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (thread_id, json.dumps(email), triage, status,
                 json.dumps(pending) if pending else None, _now()))
            self.conn.commit()

    def get_runs(self, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM runs", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        rows = self.conn.execute(q + " ORDER BY updated_at DESC", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["email"] = json.loads(d.pop("email_json"))
            d["pending"] = json.loads(d["pending"]) if d["pending"] else None
            out.append(d)
        return out

    def has_run(self, thread_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM runs WHERE thread_id=?", (thread_id,)).fetchone() is not None


def format_preferences(prefs: list[dict]) -> str:
    if not prefs:
        return "(none yet)"
    return "\n".join(f"- {p['text']}" for p in prefs)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
