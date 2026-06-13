from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import io
import mailbox
import tempfile
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from email.header import decode_header as _decode_header

from charset_normalizer import from_bytes

from src.config.logging import get_logger
from src.models.email import Attachment, EmailRecord

logger = get_logger(module="mbox_parser")


def _safe_decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = _decode_header(value)
        decoded: list[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                if charset:
                    try:
                        decoded.append(part.decode(charset, errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        result = from_bytes(part)
                        decoded.append(str(result.best()) if result.best() else part.decode("utf-8", errors="replace"))
                else:
                    result = from_bytes(part)
                    decoded.append(str(result.best()) if result.best() else part.decode("utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)
    except Exception:
        return str(value)


def _parse_address(addr: str | None) -> tuple[str, str]:
    if not addr:
        return "", ""
    name, address = email.utils.parseaddr(addr)
    return _safe_decode_header(name), address.lower()


def _parse_address_list(value: str | None) -> list[str]:
    if not value:
        return []
    addresses = email.utils.getaddresses([value])
    return [addr.lower() for _, addr in addresses if addr]


def _parse_date(date_str: str | None) -> tuple[datetime | None, str]:
    if not date_str:
        return None, ""
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        utc = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return utc, str(parsed.tzinfo) if parsed.tzinfo else ""
    except Exception:
        return None, date_str


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    text_body = ""
    html_body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if "attachment" in disp:
                    continue
                try:
                    raw_payload = part.get_payload(decode=True)
                    if not isinstance(raw_payload, bytes):
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        decoded = raw_payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        result = from_bytes(raw_payload)
                        decoded = str(result.best()) if result.best() else raw_payload.decode("utf-8", errors="replace")

                    if ct == "text/plain" and not text_body:
                        text_body = decoded
                    elif ct == "text/html" and not html_body:
                        html_body = decoded
                except Exception:
                    continue
        else:
            raw_payload = msg.get_payload(decode=True)
            if isinstance(raw_payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                try:
                    decoded = raw_payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    result = from_bytes(raw_payload)
                    decoded = str(result.best()) if result.best() else raw_payload.decode("utf-8", errors="replace")
                if msg.get_content_type() == "text/html":
                    html_body = decoded
                else:
                    text_body = decoded
    except Exception as e:
        logger.warning("body_extraction_error", error=str(e))
    return text_body, html_body


def _extract_attachments(msg: email.message.Message) -> list[Attachment]:
    attachments: list[Attachment] = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" not in disp and "inline" not in disp:
            continue
        if part.get_content_type() in ("text/plain", "text/html") and "attachment" not in disp:
            continue
        filename = part.get_filename()
        if filename:
            filename = _safe_decode_header(filename)
        else:
            filename = f"unnamed_{uuid.uuid4().hex[:8]}"
        payload = part.get_payload(decode=True)
        size = len(payload) if payload else 0
        attachments.append(
            Attachment(
                filename=filename,
                mime_type=part.get_content_type(),
                size_bytes=size,
            )
        )
    return attachments


def _compute_thread_id(msg: email.message.Message, message_id: str) -> str:
    refs = msg.get("References", "")
    in_reply_to = msg.get("In-Reply-To", "")
    if refs:
        first_ref = refs.strip().split()[0].strip("<>")
        return hashlib.md5(first_ref.encode()).hexdigest()
    if in_reply_to:
        return hashlib.md5(in_reply_to.strip().strip("<>").encode()).hexdigest()
    return hashlib.md5(message_id.encode()).hexdigest()


def parse_message(msg: email.message.Message, offset: int = 0) -> EmailRecord:
    message_id = msg.get("Message-ID", "").strip().strip("<>")
    if not message_id:
        message_id = f"generated-{uuid.uuid4().hex}"

    from_name, from_address = _parse_address(msg.get("From"))
    date_utc, date_tz = _parse_date(msg.get("Date"))
    text_body, html_body = _extract_body(msg)
    attachments = _extract_attachments(msg)

    refs_raw = msg.get("References", "")
    references = [r.strip("<>") for r in refs_raw.split() if r.strip()] if refs_raw else []
    in_reply_to = msg.get("In-Reply-To", "").strip().strip("<>")

    size = len(msg.as_bytes()) if hasattr(msg, "as_bytes") else len(str(msg))

    return EmailRecord(
        message_id=message_id,
        date_utc=date_utc,
        date_original_tz=date_tz,
        from_address=from_address,
        from_name=from_name,
        to_addresses=_parse_address_list(msg.get("To")),
        cc_addresses=_parse_address_list(msg.get("Cc")),
        bcc_addresses=_parse_address_list(msg.get("Bcc")),
        subject=_safe_decode_header(msg.get("Subject")),
        body_text=text_body,
        body_html=html_body,
        in_reply_to=in_reply_to,
        references=references,
        thread_id=_compute_thread_id(msg, message_id),
        has_attachments=len(attachments) > 0,
        attachment_count=len(attachments),
        attachments=attachments,
        size_bytes=size,
        raw_offset=offset,
    )


def parse_mbox_stream(stream: io.IOBase | bytes, start_offset: int = 0) -> Generator[EmailRecord, None, None]:
    """Parse mbox data from a stream, yielding EmailRecord objects."""
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=True) as tmp:
        if isinstance(stream, bytes):
            tmp.write(stream)
        else:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                tmp.write(chunk)
        tmp.flush()

        mbox = mailbox.mbox(tmp.name)
        offset = start_offset
        for i, msg in enumerate(mbox):
            try:
                record = parse_message(msg, offset=offset)
                yield record
                offset += 1
            except Exception as e:
                logger.warning("parse_error", index=i, error=str(e))
                yield EmailRecord(
                    message_id=f"error-{uuid.uuid4().hex}",
                    parse_error=True,
                    parse_error_detail=str(e),
                    raw_offset=offset,
                )
                offset += 1
        mbox.close()
