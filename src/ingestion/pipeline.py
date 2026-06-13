from __future__ import annotations

from datetime import datetime

from src.config.logging import get_logger
from src.ingestion.mbox_parser import parse_mbox_stream
from src.ingestion.s3_client import S3Client
from src.models.email import EmailRecord, IngestionManifest
from src.storage.database import DatabaseManager

logger = get_logger(module="ingestion_pipeline")

_BATCH_SIZE = 200


class IngestionPipeline:
    def __init__(self, db: DatabaseManager, s3: S3Client | None = None) -> None:
        self._db = db
        self._s3 = s3 or S3Client()

    def should_ingest(self) -> tuple[bool, str]:
        """Check if ingestion is needed by comparing S3 ETag with manifest."""
        manifest = self._db.get_manifest()
        try:
            meta = self._s3.get_object_metadata()
        except Exception as e:
            logger.error("s3_metadata_failed", error=str(e))
            return False, f"Cannot reach S3: {e}"

        current_etag = meta["etag"]

        if manifest is None:
            return True, "No previous ingestion found — full ingestion needed"

        if manifest.s3_etag != current_etag:
            return True, f"Archive changed (ETag: {manifest.s3_etag} -> {current_etag})"

        if not manifest.completed:
            return True, "Previous ingestion incomplete — resuming"

        return False, f"Archive up to date ({manifest.total_messages} emails indexed)"

    def run(self, force: bool = False) -> IngestionManifest:
        """Run the ingestion pipeline: stream mbox from S3, parse, store in DuckDB."""
        manifest = self._db.get_manifest()
        meta = self._s3.get_object_metadata()
        current_etag = meta["etag"]

        start_offset = 0
        if manifest and not force:
            if manifest.s3_etag == current_etag and manifest.completed:
                logger.info("ingestion_skipped", reason="up_to_date", total=manifest.total_messages)
                return manifest
            if manifest.s3_etag == current_etag and not manifest.completed:
                start_offset = manifest.last_offset
                logger.info("ingestion_resume", from_offset=start_offset)

        new_manifest = IngestionManifest(
            s3_etag=current_etag,
            s3_last_modified=meta["last_modified"],
            last_offset=start_offset,
            total_messages=manifest.total_messages if manifest else 0,
            created_at=datetime.utcnow(),
        )

        logger.info("ingestion_start", etag=current_etag, start_offset=start_offset)

        stream = self._s3.stream_object(start_byte=0)

        batch: list[EmailRecord] = []
        total_processed = 0
        error_count = 0

        for record in parse_mbox_stream(stream, start_offset=start_offset):
            if record.raw_offset < start_offset:
                continue

            if record.parse_error:
                error_count += 1

            batch.append(record)

            if len(batch) >= _BATCH_SIZE:
                inserted = self._db.insert_emails_batch(batch)
                total_processed += inserted
                new_manifest.last_offset = record.raw_offset
                new_manifest.total_messages = (manifest.total_messages if manifest else 0) + total_processed
                new_manifest.error_count = error_count
                self._db.save_manifest(new_manifest)
                logger.info("ingestion_batch", processed=total_processed, errors=error_count)
                batch = []

        if batch:
            inserted = self._db.insert_emails_batch(batch)
            total_processed += inserted

        new_manifest.total_messages = self._db.get_total_email_count()
        new_manifest.error_count = error_count
        new_manifest.completed = True
        new_manifest.last_offset = start_offset + total_processed + error_count
        self._db.save_manifest(new_manifest)

        logger.info("ingestion_complete", total=new_manifest.total_messages, errors=error_count)

        self._db.create_fts_index()

        return new_manifest

    def run_from_file(self, file_path: str, force: bool = False) -> IngestionManifest:
        """Run ingestion from a local mbox file (for testing / offline use)."""
        manifest = self._db.get_manifest()
        start_offset = 0
        if manifest and not force and manifest.completed:
            logger.info("ingestion_skipped_local", total=manifest.total_messages)
            return manifest

        logger.info("ingestion_start_local", file=file_path)

        with open(file_path, "rb") as f:
            data = f.read()

        batch: list[EmailRecord] = []
        total_processed = 0
        error_count = 0

        for record in parse_mbox_stream(data, start_offset=start_offset):
            if record.parse_error:
                error_count += 1
            batch.append(record)
            if len(batch) >= _BATCH_SIZE:
                inserted = self._db.insert_emails_batch(batch)
                total_processed += inserted
                batch = []

        if batch:
            inserted = self._db.insert_emails_batch(batch)
            total_processed += inserted

        new_manifest = IngestionManifest(
            s3_etag="local",
            s3_last_modified="",
            last_offset=total_processed + error_count,
            total_messages=self._db.get_total_email_count(),
            error_count=error_count,
            created_at=datetime.utcnow(),
            completed=True,
        )
        self._db.save_manifest(new_manifest)
        logger.info("ingestion_complete_local", total=new_manifest.total_messages, errors=error_count)
        self._db.create_fts_index()
        return new_manifest
