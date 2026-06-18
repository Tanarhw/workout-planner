import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / "workout-planner" / "data" / "planner.db"


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS week_plans (
                week_start TEXT PRIMARY KEY,
                plan_json  TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()


def save_plan(week_start: date, plan: dict) -> None:
    now = datetime.utcnow().isoformat()
    with db() as conn:
        conn.execute("""
            INSERT INTO week_plans (week_start, plan_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                plan_json  = excluded.plan_json,
                updated_at = excluded.updated_at
        """, (week_start.isoformat(), json.dumps(plan), now, now))
        conn.commit()


def get_plan(week_start: date) -> Optional[dict]:
    with db() as conn:
        row = conn.execute(
            "SELECT plan_json FROM week_plans WHERE week_start = ?",
            (week_start.isoformat(),)
        ).fetchone()
    return json.loads(row["plan_json"]) if row else None


def list_plans(limit: int = 10) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT week_start, plan_json FROM week_plans ORDER BY week_start DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [{"week_start": r["week_start"], **json.loads(r["plan_json"])} for r in rows]


def mark_session_done(week_start: date, session_date: str, session_type: str, done: bool = True) -> bool:
    plan = get_plan(week_start)
    if not plan:
        return False
    for session in plan.get("sessions", []):
        if session["date"] == session_date and session["type"] == session_type:
            session["completed"] = done
    save_plan(week_start, plan)
    return True
