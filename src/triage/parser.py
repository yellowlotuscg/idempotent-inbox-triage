from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

from .models import Attachment, EmailMessage


def parse_eml_bytes(data: bytes, source: str = "<bytes>") -> EmailMessage:
    message = BytesParser(policy=policy.default).parsebytes(data)

    raw_sender = message.get("From", "").strip()
    sender = parseaddr(raw_sender)[1] or raw_sender
    message_id = message.get("Message-ID", "").strip()
    if not sender or "@" not in sender:
        raise ValueError(f"{source}: missing a usable From header")
    if not message_id:
        raise ValueError(f"{source}: missing Message-ID header")

    plain_parts: list[str] = []
    attachments: list[Attachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True) or b""
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            attachments.append(
                Attachment(
                    filename=filename or "attachment",
                    content_type=part.get_content_type(),
                    size=len(payload),
                )
            )
        elif part.get_content_type() == "text/plain":
            plain_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))

    headers = {key.lower(): str(value) for key, value in message.items()}
    return EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=str(message.get("Subject", "")),
        body="\n".join(plain_parts),
        headers=headers,
        attachments=tuple(attachments),
    )


def parse_eml(path: str | Path) -> EmailMessage:
    source = Path(path)
    return parse_eml_bytes(source.read_bytes(), str(source))
