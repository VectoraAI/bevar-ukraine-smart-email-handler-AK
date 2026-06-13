from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from src.agents.orchestrator import Orchestrator
from src.storage.database import get_database

router = APIRouter()


def get_orchestrator() -> Orchestrator:
    db = get_database()
    return Orchestrator(db)


@router.post("/api/query")
async def process_query(
    request: Request,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Process a natural language query against the email archive."""
    body = await request.json()
    user_query: str = body.get("query", "")
    session_id: str = body.get("session_id", "")
    page: int = body.get("page", 1)
    page_size: int = body.get("page_size", 50)

    if not user_query.strip():
        return {"error": "Query cannot be empty"}

    client_ip = request.client.host if request.client else ""

    result = orchestrator.process_query(
        user_query=user_query,
        session_id=session_id or None,
        page=page,
        page_size=page_size,
        ip_address=client_ip,
    )
    return result.model_dump()


@router.get("/api/email/{message_id}")
async def get_email(
    message_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Get a single email by message_id."""
    email = orchestrator.get_email_detail(message_id)
    if not email:
        return {"error": "Email not found"}
    return {"email": email}


@router.get("/api/thread/{thread_id}")
async def get_thread(
    thread_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Get all emails in a thread."""
    emails = orchestrator.get_thread(thread_id)
    return {"emails": emails, "count": len(emails)}


@router.get("/api/stats")
async def get_stats(
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    """Get archive overview statistics."""
    return orchestrator.get_archive_overview()


@router.get("/api/top-senders")
async def top_senders(
    limit: int = Query(default=20, ge=1, le=100),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    result = orchestrator.get_top_senders(limit)
    return result.model_dump()


@router.get("/api/timeline")
async def timeline(
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> dict[str, Any]:
    result = orchestrator.get_emails_over_time()
    return result.model_dump()


@router.get("/api/export/csv")
async def export_csv(
    q: str = Query(default="", description="Search query for export"),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Response:
    """Export current query results as CSV."""
    csv_content = orchestrator.export_csv(q)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bevar-emails-export.csv"},
    )


@router.get("/api/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    try:
        db = get_database()
        count = db.get_total_email_count()
        return {"status": "healthy", "emails_indexed": str(count)}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/api/ingestion/status")
async def ingestion_status() -> dict[str, Any]:
    """Get current ingestion status."""
    db = get_database()
    manifest = db.get_manifest()
    if not manifest:
        return {"status": "not_started", "total_messages": 0}
    return {
        "status": "completed" if manifest.completed else "in_progress",
        "total_messages": manifest.total_messages,
        "error_count": manifest.error_count,
        "s3_etag": manifest.s3_etag,
        "last_modified": manifest.s3_last_modified,
    }


@router.post("/api/ingestion/trigger")
async def trigger_ingestion(request: Request) -> dict[str, Any]:
    """Trigger ingestion from S3 (admin endpoint)."""
    from src.ingestion.pipeline import IngestionPipeline
    from src.ingestion.s3_client import S3Client

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    force = body.get("force", False)

    db = get_database()
    try:
        s3 = S3Client()
        pipeline = IngestionPipeline(db, s3)
        manifest = pipeline.run(force=force)
        return {
            "status": "completed",
            "total_messages": manifest.total_messages,
            "error_count": manifest.error_count,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
