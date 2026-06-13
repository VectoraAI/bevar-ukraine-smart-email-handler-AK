from __future__ import annotations

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.ingestion.mbox_parser import _parse_address, _safe_decode_header, parse_message


class TestSafeDecodeHeader:
    def test_plain_ascii(self) -> None:
        assert _safe_decode_header("Hello World") == "Hello World"

    def test_none_input(self) -> None:
        assert _safe_decode_header(None) == ""

    def test_encoded_utf8(self) -> None:
        result = _safe_decode_header("=?UTF-8?B?0J/RgNC40LLRltGC?=")
        assert result  # Should decode Ukrainian "Привіт"

    def test_empty_string(self) -> None:
        assert _safe_decode_header("") == ""


class TestParseAddress:
    def test_full_address(self) -> None:
        name, addr = _parse_address("Alice Smith <alice@bevar.org>")
        assert name == "Alice Smith"
        assert addr == "alice@bevar.org"

    def test_bare_address(self) -> None:
        name, addr = _parse_address("alice@bevar.org")
        assert addr == "alice@bevar.org"

    def test_none(self) -> None:
        name, addr = _parse_address(None)
        assert name == ""
        assert addr == ""


class TestParseMessage:
    def test_basic_email(self) -> None:
        msg = MIMEText("Hello world", "plain", "utf-8")
        msg["From"] = "Alice <alice@bevar.org>"
        msg["To"] = "bob@bevar.org"
        msg["Subject"] = "Test subject"
        msg["Date"] = "Mon, 15 Jan 2024 10:30:00 +0100"
        msg["Message-ID"] = "<test123@bevar.org>"

        record = parse_message(msg)
        assert record.message_id == "test123@bevar.org"
        assert record.from_address == "alice@bevar.org"
        assert record.from_name == "Alice"
        assert record.subject == "Test subject"
        assert "Hello world" in record.body_text
        assert record.date_utc is not None
        assert not record.parse_error

    def test_multipart_with_attachment(self) -> None:
        msg = MIMEMultipart()
        msg["From"] = "alice@bevar.org"
        msg["To"] = "bob@bevar.org"
        msg["Subject"] = "With attachment"
        msg["Message-ID"] = "<attach@bevar.org>"
        msg["Date"] = "Mon, 15 Jan 2024 10:30:00 +0000"

        msg.attach(MIMEText("Body text", "plain"))

        attachment = MIMEText("file content", "plain")
        attachment.add_header("Content-Disposition", "attachment", filename="report.txt")
        msg.attach(attachment)

        record = parse_message(msg)
        assert record.has_attachments
        assert record.attachment_count == 1
        assert record.attachments[0].filename == "report.txt"

    def test_missing_message_id(self) -> None:
        msg = MIMEText("Hello", "plain")
        msg["From"] = "test@test.com"
        record = parse_message(msg)
        assert record.message_id.startswith("generated-")

    def test_thread_detection(self) -> None:
        msg = MIMEText("Reply", "plain")
        msg["From"] = "bob@bevar.org"
        msg["Message-ID"] = "<reply@bevar.org>"
        msg["In-Reply-To"] = "<original@bevar.org>"
        msg["References"] = "<original@bevar.org>"

        record = parse_message(msg)
        assert record.thread_id
        assert record.in_reply_to == "original@bevar.org"
