from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from .models import Decision, EmailMessage, RuleTrace


def load_rules(path: str | Path) -> tuple[str, list[dict[str, Any]]]:
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    version = str(document.get("version", "unversioned"))
    rules = document.get("rules", [])
    if not isinstance(rules, list) or len(rules) != 10:
        raise ValueError("rules file must contain exactly 10 rules")
    return version, rules


def make_idempotency_key(message_id: str, rule_set_version: str) -> str:
    return hashlib.sha256(f"{message_id}{rule_set_version}".encode("utf-8")).hexdigest()


def _condition(result: bool, name: str, expected: Any, actual: Any, reason: str) -> dict[str, Any]:
    return {"condition": name, "matched": result, "expected": expected, "actual": actual, "reason": reason}


class RuleEngine:
    def __init__(self, rule_set_version: str, rules: list[dict[str, Any]]):
        self.rule_set_version = rule_set_version
        self.rules = rules

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuleEngine":
        version, rules = load_rules(path)
        return cls(version, rules)

    def evaluate(self, message: EmailMessage) -> Decision:
        traces: list[RuleTrace] = []
        matched_rules: list[str] = []
        actions: list[dict[str, Any]] = []
        for rule in self.rules:
            rule_id = str(rule["id"])
            conditions: list[dict[str, Any]] = []
            match = rule.get("match", {})
            if "from" in match:
                expected = str(match["from"]).lower()
                actual = message.sender.lower()
                ok = actual == expected
                conditions.append(_condition(ok, "from", expected, actual, "sender equals configured address"))
            if "domain" in match:
                expected = str(match["domain"]).lower()
                actual = message.domain
                ok = actual == expected
                conditions.append(_condition(ok, "domain", expected, actual, "sender domain equals configured domain"))
            if "subject_regex" in match:
                expression = str(match["subject_regex"])
                try:
                    ok = re.search(expression, message.subject) is not None
                    reason = "regular expression matched subject" if ok else "regular expression did not match subject"
                except re.error as exc:
                    raise ValueError(f"invalid regex in {rule_id}: {exc}") from exc
                conditions.append(_condition(ok, "subject_regex", expression, message.subject, reason))
            if "body_keywords" in match:
                keywords = [str(word).lower() for word in match["body_keywords"]]
                body = message.body.lower()
                found = [word for word in keywords if word in body]
                ok = len(found) == len(keywords)
                conditions.append(_condition(ok, "body_keywords", keywords, found, f"found {len(found)}/{len(keywords)} keywords"))
            if "headers" in match:
                header_results = []
                for header, expected_value in match["headers"].items():
                    actual = message.headers.get(str(header).lower())
                    header_results.append(actual == str(expected_value))
                    conditions.append(_condition(
                        actual == str(expected_value), "header", {str(header).lower(): str(expected_value)}, {str(header).lower(): actual}, "header value comparison"
                    ))
                ok = all(header_results)
            if "attachments" in match:
                attachment_rule = match["attachments"] or {}
                extensions = [str(item).lower().lstrip(".") for item in attachment_rule.get("extensions", [])]
                actual_extensions = [Path(item.filename).suffix.lower().lstrip(".") for item in message.attachments]
                ok = bool(message.attachments) and (not extensions or any(ext in actual_extensions for ext in extensions))
                conditions.append(_condition(ok, "attachments", extensions, actual_extensions, "attachment presence and extension comparison"))
            rule_matched = bool(conditions) and all(item["matched"] for item in conditions)
            traces.append(RuleTrace(rule_id=rule_id, matched=rule_matched, conditions=conditions, actions=rule.get("actions", {})))
            if rule_matched:
                matched_rules.append(rule_id)
                for action, value in rule.get("actions", {}).items():
                    actions.append({"type": action, "value": value, "rule_id": rule_id})
        return Decision(
            message_id=message.message_id,
            rule_set_version=self.rule_set_version,
            idempotency_key=make_idempotency_key(message.message_id, self.rule_set_version),
            matched_rules=matched_rules,
            actions=actions,
            trace=traces,
        )
