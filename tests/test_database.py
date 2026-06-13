from __future__ import annotations

from datetime import datetime

from src.models.email import EmailRecord, IngestionManifest
from src.storage.database import DatabaseManager


class TestDatabaseManager:
    def test_initialize(self, db: DatabaseManager) -> None:
        count = db.get_total_email_count()
        assert count == 0

    def test_insert_and_retrieve(self, db: DatabaseManager) -> None:
        email = EmailRecord(
            message_id="test-123",
            from_address="alice@bevar.org",
            from_name="Alice",
            to_addresses=["bob@bevar.org"],
            subject="Test email",
            body_text="Hello Bob",
            date_utc=datetime(2024, 1, 15, 10, 0, 0),
        )
        db.insert_email(email)

        result = db.get_email_by_id("test-123")
        assert result is not None
        assert result["from_address"] == "alice@bevar.org"
        assert result["subject"] == "Test email"

    def test_search_filtered_no_limit(self, db: DatabaseManager) -> None:
        for i in range(10):
            email = EmailRecord(
                message_id=f"msg-{i}",
                from_address=f"user{i}@test.com",
                subject=f"Subject {i}",
                date_utc=datetime(2024, 1, i + 1, 10, 0),
            )
            db.insert_email(email)

        result = db.search_filtered(page=1, page_size=100)
        assert result.total_count == 10
        assert len(result.items) == 10

    def test_search_filtered_with_filter(self, db: DatabaseManager) -> None:
        for i in range(5):
            email = EmailRecord(
                message_id=f"filtered-{i}",
                from_address="alice@bevar.org" if i < 3 else "bob@bevar.org",
                subject=f"Subject {i}",
                date_utc=datetime(2024, 1, i + 1, 10, 0),
            )
            db.insert_email(email)

        result = db.search_filtered(
            where_clauses=["from_address = $1"],
            params={"from": "alice@bevar.org"},
        )
        assert result.total_count == 3

    def test_pagination(self, db: DatabaseManager) -> None:
        for i in range(25):
            email = EmailRecord(
                message_id=f"pag-{i}",
                from_address="sender@test.com",
                subject=f"Email {i}",
                date_utc=datetime(2024, 1, 1, i % 24, 0),
            )
            db.insert_email(email)

        page1 = db.search_filtered(page=1, page_size=10)
        assert page1.total_count == 25
        assert len(page1.items) == 10
        assert page1.total_pages == 3

        page3 = db.search_filtered(page=3, page_size=10)
        assert len(page3.items) == 5

    def test_manifest(self, db: DatabaseManager) -> None:
        assert db.get_manifest() is None

        manifest = IngestionManifest(
            s3_etag="abc123",
            total_messages=100,
            completed=True,
        )
        db.save_manifest(manifest)

        loaded = db.get_manifest()
        assert loaded is not None
        assert loaded.s3_etag == "abc123"
        assert loaded.total_messages == 100
        assert loaded.completed is True

    def test_archive_stats(self, db: DatabaseManager) -> None:
        for i in range(5):
            email = EmailRecord(
                message_id=f"stat-{i}",
                from_address=f"user{i % 3}@test.com",
                date_utc=datetime(2024, 1, i + 1, 10, 0),
                has_attachments=i % 2 == 0,
            )
            db.insert_email(email)

        stats = db.get_archive_stats()
        assert stats["total_emails"] == 5
        assert stats["unique_senders"] == 3
        assert stats["with_attachments"] == 3

    def test_audit_log(self, db: DatabaseManager) -> None:
        db.log_audit("user1", "query", "search for grants", 42, "127.0.0.1")
        results = db.aggregate_query("SELECT * FROM audit_log")
        assert len(results) == 1
        assert results[0]["query_text"] == "search for grants"

    def test_export_csv(self, db: DatabaseManager) -> None:
        email = EmailRecord(
            message_id="csv-1",
            from_address="alice@bevar.org",
            subject="CSV Test",
            date_utc=datetime(2024, 1, 15, 10, 0),
        )
        db.insert_email(email)

        csv = db.export_filtered_csv()
        assert "alice@bevar.org" in csv
        assert "CSV Test" in csv
