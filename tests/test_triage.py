from __future__ import annotations

import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

from triage.cli import main
from triage.engine import RuleEngine
from triage.models import EmailMessage as ParsedMessage
from triage.outbox import OutboxRelay
from triage.parser import parse_eml
from triage.store import SQLiteRepository

ROOT = Path(__file__).parents[1]
RULES = ROOT / "rules" / "rules.yaml"


def message(message_id: str = "<test-1@example.com>", body: str = "Please help with a widget") -> ParsedMessage:
    return ParsedMessage(
        message_id=message_id,
        sender="ava@example.com",
        subject="Widget help",
        body=body,
        headers={"from": "ava@example.com"},
    )


def engine(version: str | None = None) -> RuleEngine:
    loaded = RuleEngine.from_yaml(RULES)
    if version:
        loaded.rule_set_version = version
    return loaded


def test_duplicate_delivery_creates_one_action_set():
    repo = SQLiteRepository()
    result = None
    for _ in range(5):
        result = repo.process(message(), engine())
    assert result is not None
    assert result.persisted is False
    assert repo.count("decisions") == 1
    assert repo.count("outbox") == 2  # support label + forward action


def test_relay_crash_then_retry_has_one_effect_per_action():
    repo = SQLiteRepository()
    repo.process(message(), engine())
    relay = OutboxRelay(repo)
    with pytest.raises(RuntimeError, match="after consumer"):
        relay.relay(fault_after_send=True)
    relay.relay()
    assert repo.count("consumer_effects") == repo.count("outbox")
    assert all(row["status"] == "sent" for row in repo.outbox_rows())


def test_crash_before_commit_persists_nothing_then_retry():
    repo = SQLiteRepository()
    with pytest.raises(RuntimeError, match="before commit"):
        repo.process(message(), engine(), fault_before_commit=True)
    assert repo.count("idempotency_keys") == 0
    assert repo.count("decisions") == 0
    assert repo.count("outbox") == 0
    assert repo.process(message(), engine()).persisted is True


def test_rule_version_bump_creates_new_key():
    repo = SQLiteRepository()
    first = repo.process(message(), engine("2026-01"))
    second = repo.process(message(), engine("2026-02"))
    assert first.decision.idempotency_key != second.decision.idempotency_key
    assert repo.count("decisions") == 2


def test_dry_run_writes_no_outbox():
    repo = SQLiteRepository()
    result = repo.process(message(), engine(), dry_run=True)
    assert result.dry_run is True
    assert result.persisted is False
    assert repo.count("decisions") == 0
    assert repo.count("outbox") == 0


def test_why_cli_output(tmp_path, capsys):
    path = tmp_path / "why.eml"
    raw = EmailMessage()
    raw["From"] = "Ava Quill <ava@example.com>"
    raw["Message-ID"] = "<why@example.com>"
    raw["Subject"] = "Widget help"
    raw.set_content("Please help with a widget")
    path.write_bytes(raw.as_bytes())
    assert main(["--rules", str(RULES), "why", str(path)]) == 0
    output = capsys.readouterr().out
    assert "rule widget-support: MATCH" in output
    assert "body_keywords" in output
    assert "forward=support@example.com" in output


def test_all_seeded_fixtures_process_without_errors():
    fixture_dir = ROOT / "fixtures" / "eml"
    assert len(list(fixture_dir.glob("*.eml"))) == 200
    repo = SQLiteRepository()
    loaded = engine()
    for path in sorted(fixture_dir.glob("*.eml")):
        repo.process_path(str(path), loaded)
    assert repo.count("decisions") == 200


def test_parser_extracts_attachments_and_display_name(tmp_path):
    path = tmp_path / "attachment.eml"
    raw = EmailMessage()
    raw["From"] = "Morgan Vale <morgan@example.net>"
    raw["Message-ID"] = "<attachment@example.net>"
    raw["Subject"] = "Partner integration"
    raw.set_content("Partner integration help")
    raw.add_attachment(b"pdf", maintype="application", subtype="pdf", filename="brief.pdf")
    path.write_bytes(raw.as_bytes())
    parsed = parse_eml(path)
    assert parsed.sender == "morgan@example.net"
    assert parsed.attachments[0].filename == "brief.pdf"
