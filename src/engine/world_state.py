"""WorldState: SQLite-backed simulation state with per-tick snapshots."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class WorldState:
    """Persistent world state backed by SQLite.

    One table per tool surface. Snapshots serialize full state as JSON
    at each tick for evaluation and future replay.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.flags: dict[str, bool] = {}
        self._create_tables()

    def _create_tables(self):
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick INTEGER NOT NULL,
                channel TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick INTEGER NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                assignee TEXT,
                status TEXT NOT NULL DEFAULT 'todo',
                description TEXT DEFAULT '',
                created_tick INTEGER NOT NULL DEFAULT 0,
                updated_tick INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                tick INTEGER NOT NULL,
                duration_ticks INTEGER NOT NULL DEFAULT 1,
                attendees TEXT NOT NULL,
                agenda TEXT DEFAULT '',
                created_by TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL DEFAULT '',
                author TEXT DEFAULT '',
                created_tick INTEGER NOT NULL DEFAULT 0,
                updated_tick INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS meeting_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_title TEXT NOT NULL,
                tick INTEGER NOT NULL,
                attendees TEXT NOT NULL,
                transcript TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                tick INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tick INTEGER NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                params TEXT NOT NULL,
                success INTEGER NOT NULL,
                error TEXT
            );
        """)
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple]) -> sqlite3.Cursor:
        return self.conn.executemany(sql, params)

    def commit(self):
        self.conn.commit()

    def set_flag(self, name: str, value: bool = True):
        self.flags[name] = value

    def get_flag(self, name: str) -> bool:
        return self.flags.get(name, False)

    def log_action(
        self,
        time_or_tick,
        actor: str,
        action: str,
        params: dict,
        success: bool,
        error: str | None = None,
    ):
        # Accept either datetime or int for backwards compat
        from datetime import datetime
        if isinstance(time_or_tick, datetime):
            tick_val = int(time_or_tick.timestamp())
        else:
            tick_val = time_or_tick
        self.execute(
            "INSERT INTO action_log (tick, actor, action, params, success, error) VALUES (?, ?, ?, ?, ?, ?)",
            (tick_val, actor, action, json.dumps(params), int(success), error),
        )
        self.commit()

    def save_snapshot(self, tick: int):
        """Serialize full world state to a JSON blob (tick-based)."""
        state = self._build_snapshot_state()
        self.execute(
            "INSERT OR REPLACE INTO snapshots (tick, state_json) VALUES (?, ?)",
            (tick, json.dumps(state)),
        )
        self.commit()

    def save_snapshot_at_time(self, time):
        """Serialize full world state (time-based)."""
        from datetime import datetime
        if isinstance(time, datetime):
            tick_val = int(time.timestamp())
        else:
            tick_val = time
        state = self._build_snapshot_state()
        self.execute(
            "INSERT OR REPLACE INTO snapshots (tick, state_json) VALUES (?, ?)",
            (tick_val, json.dumps(state)),
        )
        self.commit()

    def _build_snapshot_state(self) -> dict:
        return {
            "messages": self._dump_table("messages"),
            "emails": self._dump_table("emails"),
            "tasks": self._dump_table("tasks"),
            "calendar_events": self._dump_table("calendar_events"),
            "documents": self._dump_table("documents"),
            "meeting_transcripts": self._dump_table("meeting_transcripts"),
            "flags": dict(self.flags),
        }

    def load_snapshot(self, tick: int) -> dict[str, Any] | None:
        row = self.execute(
            "SELECT state_json FROM snapshots WHERE tick = ?", (tick,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["state_json"])

    def _dump_table(self, table: str) -> list[dict]:
        rows = self.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]

    def get_action_log(self, tick: int | None = None) -> list[dict]:
        if tick is not None:
            rows = self.execute(
                "SELECT * FROM action_log WHERE tick = ?", (tick,)
            ).fetchall()
        else:
            rows = self.execute("SELECT * FROM action_log").fetchall()
        return [dict(row) for row in rows]

    def seed_table(self, table: str, records: list[dict]):
        """Insert seed data from scenario YAML."""
        if not records:
            return
        columns = records[0].keys()
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        for record in records:
            self.execute(sql, tuple(record.values()))
        self.commit()

    def close(self):
        self.conn.close()
