from __future__ import annotations

from src.ingestion.pipeline import IngestionPipeline
from src.storage.database import DatabaseManager


class TestIngestionPipeline:
    def test_local_ingestion(self, db: DatabaseManager, mbox_file: str) -> None:
        pipeline = IngestionPipeline(db)
        manifest = pipeline.run_from_file(mbox_file)

        assert manifest.completed is True
        assert manifest.total_messages == 5
        assert db.get_total_email_count() == 5

    def test_idempotent_ingestion(self, db: DatabaseManager, mbox_file: str) -> None:
        pipeline = IngestionPipeline(db)
        m1 = pipeline.run_from_file(mbox_file)
        m2 = pipeline.run_from_file(mbox_file)

        assert m1.total_messages == m2.total_messages
        assert m2.completed is True

    def test_force_reingestion(self, db: DatabaseManager, mbox_file: str) -> None:
        pipeline = IngestionPipeline(db)
        pipeline.run_from_file(mbox_file)
        manifest = pipeline.run_from_file(mbox_file, force=True)

        assert manifest.completed is True
        assert manifest.total_messages == 5

    def test_emails_have_correct_fields(self, populated_db: DatabaseManager) -> None:
        email = populated_db.get_email_by_id("msg001@bevar.org")
        assert email is not None
        assert email["from_address"] == "alice@bevar.org"
        assert email["subject"] == "Grant application update"
        assert "GlobalGiving" in email["body_text"]

    def test_thread_detection(self, populated_db: DatabaseManager) -> None:
        e1 = populated_db.get_email_by_id("msg001@bevar.org")
        e2 = populated_db.get_email_by_id("msg002@globalgiving.org")
        assert e1 is not None and e2 is not None
        assert e2["thread_id"] == e1["thread_id"]
