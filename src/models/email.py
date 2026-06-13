from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int = 0


class EmailRecord(BaseModel):
    message_id: str
    date_utc: datetime | None = None
    date_original_tz: str = ""
    from_address: str = ""
    from_name: str = ""
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    bcc_addresses: list[str] = Field(default_factory=list)
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    in_reply_to: str = ""
    references: list[str] = Field(default_factory=list)
    thread_id: str = ""
    has_attachments: bool = False
    attachment_count: int = 0
    attachments: list[Attachment] = Field(default_factory=list)
    size_bytes: int = 0
    language: str = ""
    parse_error: bool = False
    parse_error_detail: str = ""
    raw_offset: int = 0
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class EmailSummary(BaseModel):
    """Lightweight email representation for table display."""

    message_id: str
    date_utc: str = ""
    from_address: str = ""
    from_name: str = ""
    to_addresses: str = ""
    subject: str = ""
    has_attachments: bool = False
    attachment_count: int = 0
    size_bytes: int = 0
    snippet: str = ""


class IngestionManifest(BaseModel):
    s3_etag: str = ""
    s3_last_modified: str = ""
    last_offset: int = 0
    total_messages: int = 0
    error_count: int = 0
    checksum: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed: bool = False


class PaginatedResult(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 0
