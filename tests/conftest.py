from __future__ import annotations

import mailbox
import os
import tempfile
from collections.abc import Generator
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from src.storage.database import DatabaseManager

os.environ["APP_ENV"] = "test"
os.environ["DUCKDB_PATH"] = ":memory:"
os.environ["AWS_ACCESS_KEY_ID"] = ""
os.environ["AWS_SECRET_ACCESS_KEY"] = ""
os.environ["BEDROCK_MODEL_ID"] = "us.anthropic.claude-sonnet-4-6"


@pytest.fixture
def db() -> Generator:
    """Fresh in-memory DuckDB database for each test."""
    manager = DatabaseManager(":memory:")
    manager.initialize()
    yield manager
    manager.close()


@pytest.fixture
def sample_emails() -> list[dict[str, str]]:
    return [
        {
            "from": "alice@bevar.org",
            "to": "bob@bevar.org",
            "subject": "Grant application update",
            "body": "Hello Bob, the GlobalGiving grant application has been submitted successfully.",
            "date": "Mon, 15 Jan 2024 10:30:00 +0100",
            "message_id": "<msg001@bevar.org>",
        },
        {
            "from": "carol@globalgiving.org",
            "to": "alice@bevar.org",
            "subject": "Re: Grant application update",
            "body": "Dear Alice, we have received your application. We will review it within 2 weeks.",
            "date": "Tue, 16 Jan 2024 14:00:00 +0000",
            "message_id": "<msg002@globalgiving.org>",
            "in_reply_to": "<msg001@bevar.org>",
            "references": "<msg001@bevar.org>",
        },
        {
            "from": "dave@drc.org",
            "to": "alice@bevar.org",
            "subject": "Partnership meeting agenda",
            "body": "Hi Alice, please find the agenda for our upcoming partnership meeting attached.",
            "date": "Wed, 17 Jan 2024 09:00:00 +0100",
            "message_id": "<msg003@drc.org>",
        },
        {
            "from": "alice@bevar.org",
            "to": "team@bevar.org",
            "subject": "Weekly team update",
            "body": "Hi team, here is this week's update. We have 5 new volunteers and 3 pending grants.",
            "date": "Fri, 19 Jan 2024 16:00:00 +0100",
            "message_id": "<msg004@bevar.org>",
        },
        {
            "from": "volunteer@example.com",
            "to": "alice@bevar.org",
            "subject": "Volunteer registration",
            "body": "Hello, I would like to register as a volunteer. My name is Olena and I speak Ukrainian and Danish.",
            "date": "Sat, 20 Jan 2024 11:00:00 +0100",
            "message_id": "<msg005@example.com>",
        },
    ]


@pytest.fixture
def mbox_file(sample_emails: list[dict[str, str]]) -> Generator[str, None, None]:
    """Create a temporary mbox file with sample emails."""
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False, mode="w") as f:
        path = f.name

    mbox = mailbox.mbox(path)
    for data in sample_emails:
        msg = MIMEMultipart()
        msg["From"] = data["from"]
        msg["To"] = data["to"]
        msg["Subject"] = data["subject"]
        msg["Date"] = data["date"]
        msg["Message-ID"] = data["message_id"]
        if "in_reply_to" in data:
            msg["In-Reply-To"] = data["in_reply_to"]
        if "references" in data:
            msg["References"] = data["references"]
        msg.attach(MIMEText(data["body"], "plain", "utf-8"))
        mbox.add(msg)
    mbox.close()

    yield path

    os.unlink(path)


@pytest.fixture
def populated_db(db: DatabaseManager, mbox_file: str) -> DatabaseManager:
    """DB with sample emails already ingested."""
    from src.ingestion.pipeline import IngestionPipeline

    pipeline = IngestionPipeline(db)
    pipeline.run_from_file(mbox_file, force=True)
    return db
