"""Entry point for the Bevar Ukraine Email Archive application."""
from __future__ import annotations

import sys

import uvicorn

from src.config.settings import get_settings


def main() -> None:
    settings = get_settings()

    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        run_ingestion(force="--force" in sys.argv)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "ingest-local" and len(sys.argv) > 2:
        run_local_ingestion(sys.argv[2], force="--force" in sys.argv)
        return

    uvicorn.run(
        "src.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
        log_level=settings.log_level.lower(),
    )


def run_ingestion(force: bool = False) -> None:
    from src.config.logging import setup_logging
    setup_logging()
    from src.ingestion.pipeline import IngestionPipeline
    from src.ingestion.s3_client import S3Client
    from src.storage.database import get_database

    db = get_database()
    s3 = S3Client()
    pipeline = IngestionPipeline(db, s3)

    should, reason = pipeline.should_ingest()
    print(f"Ingestion check: {reason}")
    if should or force:
        manifest = pipeline.run(force=force)
        print(f"Ingestion complete: {manifest.total_messages} emails, {manifest.error_count} errors")
    else:
        print("No ingestion needed.")


def run_local_ingestion(file_path: str, force: bool = False) -> None:
    from src.config.logging import setup_logging
    setup_logging()
    from src.ingestion.pipeline import IngestionPipeline
    from src.storage.database import get_database

    db = get_database()
    pipeline = IngestionPipeline(db)
    manifest = pipeline.run_from_file(file_path, force=force)
    print(f"Local ingestion complete: {manifest.total_messages} emails, {manifest.error_count} errors")


if __name__ == "__main__":
    main()
