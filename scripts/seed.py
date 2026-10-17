#!/usr/bin/env python3
"""Create deterministic synthetic inbound mail for local demos."""
from __future__ import annotations

import random
import sys
from email.message import EmailMessage
from pathlib import Path

NAMES = ["Avery Quill", "Morgan Vale", "Riley North", "Casey Finch", "Jordan Wren"]
DOMAINS = ["example.com", "example.org", "example.net"]
TEMPLATES = [
    ("Order request", "Please help with our widget order."),
    ("Invoice question", "The invoice charge needs a billing review."),
    ("Access review", "Please review access security for this widget."),
    ("Partner integration", "Our partner needs an integration update."),
    ("Widget help", "We need help with a widget and have feedback."),
    ("Please cancel", "Please cancel this request and unsubscribe us."),
    ("Northwind news update", "Here is the latest news update."),
    ("Receipt", "The receipt includes an invoice charge."),
]


def make_message(index: int, rng: random.Random) -> EmailMessage:
    name = NAMES[index % len(NAMES)]
    domain = DOMAINS[index % len(DOMAINS)]
    subject, body = TEMPLATES[index % len(TEMPLATES)]
    message = EmailMessage()
    message["From"] = f"{name} <{name.lower().replace(' ', '.')}@{domain}>"
    message["To"] = "triage@northwind.example.com"
    message["Message-ID"] = f"<fixture-{index:04d}@{domain}>"
    message["Date"] = "Mon, 01 Jan 2026 00:00:00 +0000"
    if index % 11 == 0:
        message["X-Priority"] = "1"
    if index % 13 == 0:
        message["X-Security-Review"] = "required"
        subject = "Security access review"
    message["Subject"] = subject
    if index % 17 == 0:
        message["List-ID"] = "northwind-news.example.org"
    message.set_content(f"Hello Northwind Widgets team,\n\n{body}\n\nReference {rng.randint(1000, 9999)}.\n")
    if index % 7 == 0:
        message.add_attachment(b"synthetic-pdf", maintype="application", subtype="pdf", filename=f"widget-{index:04d}.pdf")
        message.set_boundary(f"fixture-boundary-{index:04d}")
    return message


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures/eml")
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260101)
    for path in output.glob("*.eml"):
        path.unlink()
    for index in range(200):
        path = output / f"fixture-{index:04d}.eml"
        path.write_bytes(make_message(index, rng).as_bytes())
    print(f"generated=200 directory={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
