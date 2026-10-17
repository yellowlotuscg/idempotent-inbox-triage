from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass(frozen=True)
class EmailMessage:
    message_id: str
    sender: str
    subject: str
    body: str
    headers: dict[str, str]
    attachments: tuple[Attachment, ...] = ()

    @property
    def domain(self) -> str:
        return self.sender.rsplit("@", 1)[-1].lower()


@dataclass
class RuleTrace:
    rule_id: str
    matched: bool
    conditions: list[dict[str, Any]] = field(default_factory=list)
    actions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    message_id: str
    rule_set_version: str
    idempotency_key: str
    matched_rules: list[str]
    actions: list[dict[str, Any]]
    trace: list[RuleTrace]

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "rule_set_version": self.rule_set_version,
            "idempotency_key": self.idempotency_key,
            "matched_rules": self.matched_rules,
            "actions": self.actions,
            "trace": [
                {
                    "rule_id": t.rule_id,
                    "matched": t.matched,
                    "conditions": t.conditions,
                    "actions": t.actions,
                }
                for t in self.trace
            ],
        }
