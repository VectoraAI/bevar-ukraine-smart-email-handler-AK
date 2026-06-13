from __future__ import annotations

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import duckdb

from src.config.logging import get_logger
from src.config.settings import get_settings
from src.models.email import EmailRecord, IngestionManifest, PaginatedResult

logger = get_logger(module="storage")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS emails (
    message_id VARCHAR PRIMARY KEY,
    date_utc TIMESTAMP,
    date_original_tz VARCHAR,
    from_address VARCHAR,
    from_name VARCHAR,
    to_addresses JSON,
    cc_addresses JSON,
    bcc_addresses JSON,
    subject VARCHAR,
    body_text VARCHAR,
    body_html VARCHAR,
    in_reply_to VARCHAR,
    "references" JSON,
    thread_id VARCHAR,
    has_attachments BOOLEAN,
    attachment_count INTEGER,
    attachments JSON,
    size_bytes INTEGER,
    language VARCHAR,
    parse_error BOOLEAN DEFAULT FALSE,
    parse_error_detail VARCHAR DEFAULT '',
    raw_offset BIGINT DEFAULT 0,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_manifest (
    id INTEGER PRIMARY KEY DEFAULT 1,
    s3_etag VARCHAR,
    s3_last_modified VARCHAR,
    last_offset BIGINT DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    checksum VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER DEFAULT nextval('audit_seq'),
    user_id VARCHAR,
    action VARCHAR,
    query_text VARCHAR,
    result_count INTEGER DEFAULT 0,
    ip_address VARCHAR DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date_utc);
CREATE INDEX IF NOT EXISTS idx_emails_from ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_subject ON emails(subject);
"""


class DatabaseManager:
    def __init__(self, db_path: str | None = None) -> None:
        settings = get_settings()
        self._db_path = db_path or str(settings.duckdb_full_path)
        self._is_memory = self._db_path == ":memory:"
        self._local = threading.local()
        # For in-memory DBs, share a single connection across threads
        self._shared_conn: duckdb.DuckDBPyConnection | None = None
        if self._is_memory:
            self._shared_conn = duckdb.connect(":memory:")

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        if self._shared_conn is not None:
            return self._shared_conn
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = duckdb.connect(self._db_path)
        conn: duckdb.DuckDBPyConnection = self._local.conn
        return conn

    @contextmanager
    def connection(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = self._get_conn()
        try:
            yield conn
        except Exception:
            logger.exception("database_error")
            raise

    def initialize(self) -> None:
        with self.connection() as conn:
            try:
                conn.execute("CREATE SEQUENCE IF NOT EXISTS audit_seq START 1")
            except duckdb.CatalogException:
                pass
            conn.execute(_SCHEMA_SQL)
            logger.info("database_initialized", path=self._db_path)

    def create_fts_index(self) -> None:
        with self.connection() as conn:
            try:
                conn.execute("INSTALL fts; LOAD fts;")
                conn.execute(
                    "PRAGMA create_fts_index('emails', 'message_id', 'subject', 'body_text', 'from_address', 'from_name', overwrite=1)"
                )
                logger.info("fts_index_created")
            except Exception as e:
                logger.warning("fts_index_error", error=str(e))

    def insert_email(self, email: EmailRecord) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO emails VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23
                )
                """,
                [
                    email.message_id,
                    email.date_utc,
                    email.date_original_tz,
                    email.from_address,
                    email.from_name,
                    json.dumps(email.to_addresses),
                    json.dumps(email.cc_addresses),
                    json.dumps(email.bcc_addresses),
                    email.subject,
                    email.body_text,
                    email.body_html,
                    email.in_reply_to,
                    json.dumps(email.references),
                    email.thread_id,
                    email.has_attachments,
                    email.attachment_count,
                    json.dumps([a.model_dump() for a in email.attachments]),
                    email.size_bytes,
                    email.language,
                    email.parse_error,
                    email.parse_error_detail,
                    email.raw_offset,
                    email.ingested_at,
                ],
            )

    def insert_emails_batch(self, emails: list[EmailRecord]) -> int:
        if not emails:
            return 0
        count = 0
        with self.connection() as conn:
            for email in emails:
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO emails VALUES (
                            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23
                        )
                        """,
                        [
                            email.message_id,
                            email.date_utc,
                            email.date_original_tz,
                            email.from_address,
                            email.from_name,
                            json.dumps(email.to_addresses),
                            json.dumps(email.cc_addresses),
                            json.dumps(email.bcc_addresses),
                            email.subject,
                            email.body_text,
                            email.body_html,
                            email.in_reply_to,
                            json.dumps(email.references),
                            email.thread_id,
                            email.has_attachments,
                            email.attachment_count,
                            json.dumps([a.model_dump() for a in email.attachments]),
                            email.size_bytes,
                            email.language,
                            email.parse_error,
                            email.parse_error_detail,
                            email.raw_offset,
                            email.ingested_at,
                        ],
                    )
                    count += 1
                except Exception as e:
                    logger.warning("batch_insert_skip", message_id=email.message_id, error=str(e))
        return count

    def search_fts(self, query: str, limit: int = 0, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection() as conn:
            try:
                conn.execute("LOAD fts;")
                sql = """
                    SELECT e.*, fts_main_emails.match_bm25(message_id, $1) AS score
                    FROM emails e
                    WHERE score IS NOT NULL
                    ORDER BY score DESC
                """
                if limit > 0:
                    sql += f" LIMIT {limit} OFFSET {offset}"
                result = conn.execute(sql, [query])
                columns = [desc[0] for desc in result.description]
                return [dict(zip(columns, row)) for row in result.fetchall()]
            except Exception:
                # Fallback to ILIKE search when FTS is not available
                like_param = f"%{query}%"
                sql = """
                    SELECT *, 0.0 AS score FROM emails
                    WHERE subject ILIKE $1 OR body_text ILIKE $1
                        OR from_address ILIKE $1 OR from_name ILIKE $1
                    ORDER BY date_utc DESC
                """
                if limit > 0:
                    sql += f" LIMIT {limit} OFFSET {offset}"
                result = conn.execute(sql, [like_param])
                columns = [desc[0] for desc in result.description]
                return [dict(zip(columns, row)) for row in result.fetchall()]

    def search_filtered(
        self,
        where_clauses: list[str] | None = None,
        params: dict[str, Any] | None = None,
        order_by: str = "date_utc DESC",
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResult:
        where_sql = ""
        param_list: list[Any] = []
        if where_clauses:
            conditions = []
            for clause in where_clauses:
                conditions.append(clause)
            where_sql = "WHERE " + " AND ".join(conditions)
            if params:
                param_list = list(params.values())

        with self.connection() as conn:
            count_sql = f"SELECT COUNT(*) FROM emails {where_sql}"
            total = conn.execute(count_sql, param_list).fetchone()[0]  # type: ignore[index]

            offset = (page - 1) * page_size
            data_sql = f"""
                SELECT message_id, date_utc, from_address, from_name,
                       to_addresses, subject, has_attachments, attachment_count,
                       size_bytes, LEFT(body_text, 200) as snippet
                FROM emails {where_sql}
                ORDER BY {order_by}
                LIMIT {page_size} OFFSET {offset}
            """
            result = conn.execute(data_sql, param_list)
            columns = [desc[0] for desc in result.description]
            items = [dict(zip(columns, row)) for row in result.fetchall()]

            total_pages = max(1, (total + page_size - 1) // page_size)

        return PaginatedResult(
            items=items,
            total_count=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def aggregate_query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            result = conn.execute(sql, params or [])
            columns = [desc[0] for desc in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_email_by_id(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            result = conn.execute("SELECT * FROM emails WHERE message_id = $1", [message_id])
            columns = [desc[0] for desc in result.description]
            row = result.fetchone()
            return dict(zip(columns, row)) if row else None

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            result = conn.execute(
                "SELECT * FROM emails WHERE thread_id = $1 ORDER BY date_utc ASC",
                [thread_id],
            )
            columns = [desc[0] for desc in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_manifest(self) -> IngestionManifest | None:
        with self.connection() as conn:
            result = conn.execute("SELECT * FROM ingestion_manifest WHERE id = 1")
            row = result.fetchone()
            if not row:
                return None
            columns = [desc[0] for desc in result.description]
            data = dict(zip(columns, row))
            data.pop("id", None)
            return IngestionManifest(**data)

    def save_manifest(self, manifest: IngestionManifest) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM ingestion_manifest WHERE id = 1")
            conn.execute(
                """
                INSERT INTO ingestion_manifest (id, s3_etag, s3_last_modified, last_offset,
                    total_messages, error_count, checksum, created_at, completed)
                VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    manifest.s3_etag,
                    manifest.s3_last_modified,
                    manifest.last_offset,
                    manifest.total_messages,
                    manifest.error_count,
                    manifest.checksum,
                    manifest.created_at,
                    manifest.completed,
                ],
            )

    def log_audit(
        self, user_id: str, action: str, query_text: str, result_count: int = 0, ip_address: str = ""
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (user_id, action, query_text, result_count, ip_address)
                VALUES ($1, $2, $3, $4, $5)
                """,
                [user_id, action, query_text, result_count, ip_address],
            )

    def get_total_email_count(self) -> int:
        with self.connection() as conn:
            result = conn.execute("SELECT COUNT(*) FROM emails")
            row = result.fetchone()
            return int(row[0]) if row else 0

    def get_archive_stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            stats: dict[str, Any] = {}
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    MIN(date_utc) as earliest,
                    MAX(date_utc) as latest,
                    COUNT(CASE WHEN has_attachments THEN 1 END) as with_attachments,
                    COUNT(CASE WHEN parse_error THEN 1 END) as errors,
                    COUNT(DISTINCT from_address) as unique_senders
                FROM emails
            """).fetchone()
            if row:
                stats = {
                    "total_emails": row[0],
                    "earliest_date": str(row[1]) if row[1] else None,
                    "latest_date": str(row[2]) if row[2] else None,
                    "with_attachments": row[3],
                    "parse_errors": row[4],
                    "unique_senders": row[5],
                }
            return stats

    def export_filtered_csv(self, where_clauses: list[str] | None = None, params: dict[str, Any] | None = None) -> str:
        where_sql = ""
        param_list: list[Any] = []
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
            if params:
                param_list = list(params.values())

        with self.connection() as conn:
            sql = f"""
                SELECT message_id, date_utc, from_address, from_name,
                       to_addresses, subject, has_attachments, attachment_count, size_bytes
                FROM emails {where_sql}
                ORDER BY date_utc DESC
            """
            result = conn.execute(sql, param_list)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

        lines = [",".join(columns)]
        for row in rows:
            line = ",".join('"' + str(v).replace('"', '""') + '"' if v is not None else "" for v in row)
            lines.append(line)
        return "\n".join(lines)

    def close(self) -> None:
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None


_db_instance: DatabaseManager | None = None


def get_database(db_path: str | None = None) -> DatabaseManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager(db_path)
        _db_instance.initialize()
    return _db_instance
