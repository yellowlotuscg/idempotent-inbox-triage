from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .store import SQLiteRepository


@dataclass
class RelayStats:
    attempted: int = 0
    applied: int = 0
    duplicates: int = 0


class DedupeConsumer:
    """Consumer-side conditional insert makes retried deliveries harmless."""

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def consume(self, action_id: str, action_json: str) -> bool:
        return self.repository.apply_consumer_effect(action_id, action_json)

    @property
    def effect_count(self) -> int:
        return self.repository.count("consumer_effects")


class OutboxRelay:
    def __init__(self, repository: SQLiteRepository, consumer: DedupeConsumer | None = None):
        self.repository = repository
        self.consumer = consumer or DedupeConsumer(repository)

    def relay(self, fault_after_send: bool = False, fault_hook: Callable[[int], None] | None = None) -> RelayStats:
        stats = RelayStats()
        for row in self.repository.outbox_rows(status="pending"):
            stats.attempted += 1
            self.repository.mark_attempt(int(row["id"]))
            applied = self.consumer.consume(str(row["action_id"]), str(row["action_json"]))
            if applied:
                stats.applied += 1
            else:
                stats.duplicates += 1
            if fault_hook:
                fault_hook(stats.attempted)
            if fault_after_send and stats.attempted == 1:
                raise RuntimeError("injected crash after consumer side effect")
            self.repository.mark_sent(int(row["id"]))
        return stats

    def replay(self) -> RelayStats:
        """Re-deliver all rows, including sent rows, to demonstrate consumer dedupe."""
        stats = RelayStats()
        for row in self.repository.outbox_rows():
            stats.attempted += 1
            if self.consumer.consume(str(row["action_id"]), str(row["action_json"])):
                stats.applied += 1
            else:
                stats.duplicates += 1
        return stats


def action_text(row) -> str:
    return json.loads(row["action_json"])
