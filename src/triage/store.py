from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .engine import RuleEngine
from .models import Decision, EmailMessage
from .parser import parse_eml


class InMemoryIdempotencyStore:
    """DynamoDB PutItem(ConditionExpression attribute_not_exists) equivalent."""

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def conditional_put(self, key: str, value: Any) -> bool:
        if key in self.records:
            return False
        self.records[key] = value
        return True


class SQLiteIdempotencyStore:
    """Local conditional-put implementation backed by a unique primary key."""

    def __init__(self, connection: sqlite3.Connection | str = ":memory:"):
        self.connection = sqlite3.connect(connection) if isinstance(connection, str) else connection
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self.connection.commit()

    def conditional_put(self, key: str, value: Any) -> bool:
        payload = json.dumps(value, sort_keys=True)
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO idempotency_keys(key, payload, created_at) VALUES (?, ?, ?)",
            (key, payload, _now()),
        )
        return cursor.rowcount == 1


@dataclass
class ProcessResult:
    decision: Decision
    persisted: bool
    dry_run: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    def __init__(self, path: str = ":memory:"):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                idempotency_key TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                rule_set_version TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(idempotency_key) REFERENCES idempotency_keys(key)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL,
                action_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(idempotency_key) REFERENCES decisions(idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS consumer_effects (
                action_id TEXT PRIMARY KEY,
                action_json TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()
        self.idempotency = SQLiteIdempotencyStore(self.connection)

    def close(self) -> None:
        self.connection.close()

    def process(self, message: EmailMessage, engine: RuleEngine, dry_run: bool = False, fault_before_commit: bool = False) -> ProcessResult:
        decision = engine.evaluate(message)
        if dry_run:
            return ProcessResult(decision=decision, persisted=False, dry_run=True)
        try:
            self.connection.execute("BEGIN")
            inserted = self.idempotency.conditional_put(decision.idempotency_key, decision.as_dict())
            if inserted:
                self.connection.execute(
                    "INSERT INTO decisions(idempotency_key, message_id, rule_set_version, decision_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (decision.idempotency_key, decision.message_id, decision.rule_set_version, json.dumps(decision.as_dict(), sort_keys=True), _now()),
                )
                for action in decision.actions:
                    action_json = json.dumps(action, sort_keys=True)
                    action_id = __import__("hashlib").sha256(f"{decision.idempotency_key}:{action_json}".encode()).hexdigest()
                    self.connection.execute(
                        "INSERT INTO outbox(action_id, idempotency_key, action_json, created_at) VALUES (?, ?, ?, ?)",
                        (action_id, decision.idempotency_key, action_json, _now()),
                    )
            if fault_before_commit:
                raise RuntimeError("injected crash before commit")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return ProcessResult(decision=decision, persisted=inserted, dry_run=False)

    def process_path(self, path: str, engine: RuleEngine, dry_run: bool = False, fault_before_commit: bool = False) -> ProcessResult:
        return self.process(parse_eml(path), engine, dry_run=dry_run, fault_before_commit=fault_before_commit)

    def count(self, table: str) -> int:
        if table not in {"idempotency_keys", "decisions", "outbox", "consumer_effects"}:
            raise ValueError("unknown table")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def outbox_rows(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return list(self.connection.execute("SELECT * FROM outbox WHERE status = ? ORDER BY id", (status,)))
        return list(self.connection.execute("SELECT * FROM outbox ORDER BY id"))

    def mark_sent(self, row_id: int) -> None:
        self.connection.execute("UPDATE outbox SET status = 'sent', sent_at = ?, attempts = attempts + 1 WHERE id = ?", (_now(), row_id))
        self.connection.commit()

    def mark_attempt(self, row_id: int) -> None:
        self.connection.execute("UPDATE outbox SET attempts = attempts + 1 WHERE id = ?", (row_id,))
        self.connection.commit()

    def apply_consumer_effect(self, action_id: str, action_json: str) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO consumer_effects(action_id, action_json, applied_at) VALUES (?, ?, ?)",
            (action_id, action_json, _now()),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def effect_rows(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM consumer_effects ORDER BY applied_at, action_id"))
