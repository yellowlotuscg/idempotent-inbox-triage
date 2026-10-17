from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .engine import RuleEngine
from .outbox import OutboxRelay
from .store import SQLiteRepository


def _engine(rules: str) -> RuleEngine:
    return RuleEngine.from_yaml(rules)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m triage")
    parser.add_argument("--db", default=os.getenv("TRIAGE_DB_PATH", ".triage.sqlite"))
    parser.add_argument("--rules", default=os.getenv("TRIAGE_RULES_PATH", "rules/rules.yaml"))
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("TRIAGE_DRY_RUN", "0") == "1")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_local_options(command):
        command.add_argument("--db", default=argparse.SUPPRESS)
        command.add_argument("--rules", default=argparse.SUPPRESS)
        command.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)

    run = sub.add_parser("run", help="process .eml files in a directory")
    run.add_argument("directory")
    add_local_options(run)
    why = sub.add_parser("why", help="explain matching rules for one .eml")
    why.add_argument("eml")
    add_local_options(why)
    relay = sub.add_parser("relay", help="send pending outbox rows")
    relay.add_argument("--fault-after-send", action="store_true")
    add_local_options(relay)
    replay = sub.add_parser("replay", help="re-deliver outbox rows to the deduplicating consumer")
    replay.add_argument("--all", action="store_true", help="accepted for explicit replay semantics")
    add_local_options(replay)
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    repo = SQLiteRepository(args.db)
    engine = _engine(args.rules)
    paths = sorted(Path(args.directory).glob("*.eml"))
    persisted = 0
    for path in paths:
        result = repo.process_path(str(path), engine, dry_run=args.dry_run)
        persisted += int(result.persisted)
        print(f"{path.name}: rules={','.join(result.decision.matched_rules) or 'none'} key={result.decision.idempotency_key[:12]} persisted={result.persisted}")
    print(f"processed={len(paths)} persisted={persisted} dry_run={args.dry_run}")
    repo.close()
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    engine = _engine(args.rules)
    from .parser import parse_eml
    decision = engine.evaluate(parse_eml(args.eml))
    print(f"message_id: {decision.message_id}")
    print(f"rule_set_version: {decision.rule_set_version}")
    print(f"idempotency_key: {decision.idempotency_key}")
    print(f"matched_rules: {', '.join(decision.matched_rules) or 'none'}")
    for trace in decision.trace:
        print(f"rule {trace.rule_id}: {'MATCH' if trace.matched else 'no match'}")
        for condition in trace.conditions:
            print(f"  {'yes' if condition['matched'] else 'no'} {condition['condition']}: {condition['reason']}")
    print("actions:")
    for action in decision.actions:
        print(f"  {action['type']}={action['value']} (rule={action['rule_id']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "why":
        return cmd_why(args)
    repo = SQLiteRepository(args.db)
    if args.command == "run":
        repo.close()
        return cmd_run(args)
    relay = OutboxRelay(repo)
    if args.command == "relay":
        stats = relay.relay(fault_after_send=args.fault_after_send)
    else:
        stats = relay.replay()
    print(json.dumps(stats.__dict__, sort_keys=True))
    repo.close()
    return 0
