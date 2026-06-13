from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from src.agents.orchestrator import Orchestrator
from src.storage.database import get_database

router = APIRouter()

_ingestion_lock = threading.Lock()
_ingestion_status: dict[str, Any] = {"running": False}


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
    result: dict[str, Any] = {"running": _ingestion_status["running"]}
    if _ingestion_status.get("error"):
        result["error"] = _ingestion_status["error"]
    if not manifest:
        result["status"] = "not_started"
        result["total_messages"] = 0
    else:
        result["status"] = "completed" if manifest.completed else "in_progress"
        result["total_messages"] = manifest.total_messages
        result["error_count"] = manifest.error_count
        result["s3_etag"] = manifest.s3_etag
    return result


@router.post("/api/ingestion/trigger")
async def trigger_ingestion(request: Request) -> dict[str, Any]:
    """Trigger ingestion from S3 in a background thread."""
    from src.ingestion.pipeline import IngestionPipeline
    from src.ingestion.s3_client import S3Client

    if _ingestion_status["running"]:
        return {"status": "already_running", "progress": _ingestion_status.get("progress", {})}

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    force = body.get("force", False)

    def _run_ingestion() -> None:
        with _ingestion_lock:
            _ingestion_status["running"] = True
            _ingestion_status["error"] = None
            try:
                db = get_database()
                s3 = S3Client()
                pipeline = IngestionPipeline(db, s3)
                manifest = pipeline.run(force=force)
                _ingestion_status["progress"] = {
                    "total_messages": manifest.total_messages,
                    "error_count": manifest.error_count,
                    "completed": manifest.completed,
                }
            except Exception as e:
                _ingestion_status["error"] = str(e)
            finally:
                _ingestion_status["running"] = False

    thread = threading.Thread(target=_run_ingestion, daemon=True)
    thread.start()
    return {"status": "started", "message": "Ingestion running in background. Check /api/ingestion/status"}
