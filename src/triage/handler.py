from __future__ import annotations

import json
import os
from urllib.parse import unquote_plus

from .engine import RuleEngine
from .parser import parse_eml_bytes
from .store import SQLiteRepository


def _object_bytes(event: dict) -> bytes:
    detail = event.get("detail", {})
    if "body" in detail:
        body = detail["body"]
        return body.encode() if isinstance(body, str) else bytes(body)
    bucket = detail.get("bucket", {}).get("name") or detail.get("bucket")
    key = detail.get("object", {}).get("key") or detail.get("key")
    if not bucket or not key:
        raise ValueError("event must contain detail.bucket and detail.object.key")
    import boto3
    return boto3.client("s3").get_object(Bucket=bucket, Key=unquote_plus(key))["Body"].read()


def lambda_handler(event: dict, context) -> dict:
    """Process an EventBridge S3 Object Created event; local tests can provide detail.body."""
    rules = os.getenv("TRIAGE_RULES_PATH", "rules/rules.yaml")
    db = os.getenv("TRIAGE_DB_PATH", "/tmp/triage.sqlite")
    dry_run = os.getenv("TRIAGE_DRY_RUN", "0") == "1"
    engine = RuleEngine.from_yaml(rules)
    message = parse_eml_bytes(_object_bytes(event))
    repo = SQLiteRepository(db)
    result = repo.process(message, engine, dry_run=dry_run)
    repo.close()
    return {
        "message_id": message.message_id,
        "idempotency_key": result.decision.idempotency_key,
        "persisted": result.persisted,
        "dry_run": result.dry_run,
        "matched_rules": result.decision.matched_rules,
    }


def relay_lambda_handler(event: dict, context) -> dict:
    """Consume SQS outbox records with the same conditional consumer dedupe."""
    repo = SQLiteRepository(os.getenv("TRIAGE_DB_PATH", "/tmp/triage-relay.sqlite"))
    applied = 0
    duplicates = 0
    for record in event.get("Records", []):
        payload = json.loads(record["body"])
        if repo.apply_consumer_effect(str(payload["action_id"]), json.dumps(payload["action"], sort_keys=True)):
            applied += 1
        else:
            duplicates += 1
    repo.close()
    return {"applied": applied, "duplicates": duplicates}
