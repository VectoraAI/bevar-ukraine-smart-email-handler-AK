from __future__ import annotations

import time
from typing import Any

from src.config.logging import get_logger
from src.models.agents import QueryPlan, SearchResult
from src.models.email import PaginatedResult
from src.storage.database import DatabaseManager

logger = get_logger(module="data_access_agent")


class DataAccessAgent:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def execute_search(self, plan: QueryPlan, page: int = 1, page_size: int = 50) -> SearchResult:
        """Execute search against the full index based on QueryPlan."""
        start = time.monotonic()

        if plan.fts_query and not plan.sql_filters:
            results = self._db.search_fts(plan.fts_query)
            elapsed = (time.monotonic() - start) * 1000

            threads: dict[str, list[str]] = {}
            for r in results:
                tid = r.get("thread_id", "")
                if tid:
                    threads.setdefault(tid, []).append(r.get("message_id", ""))

            return SearchResult(
                emails=results,
                total_count=len(results),
                query_time_ms=elapsed,
                threads=threads,
            )

        paginated = self._db.search_filtered(
            where_clauses=plan.sql_filters if plan.sql_filters else None,
            params=plan.sql_params if plan.sql_params else None,
            order_by=plan.sort_clause,
            page=page,
            page_size=page_size,
        )
        elapsed = (time.monotonic() - start) * 1000

        return SearchResult(
            emails=paginated.items,
            total_count=paginated.total_count,
            query_time_ms=elapsed,
        )

    def execute_aggregation(self, plan: QueryPlan) -> list[dict[str, Any]]:
        """Execute aggregation queries based on QueryPlan."""
        where_sql = ""
        params: list[Any] = []
        if plan.sql_filters:
            where_sql = "WHERE " + " AND ".join(plan.sql_filters)
            if plan.sql_params:
                params = list(plan.sql_params.values())

        if plan.aggregation_type == "time_series":
            sql = f"""
                SELECT
                    STRFTIME(date_utc, '%Y-%m') as period,
                    COUNT(*) as count
                FROM emails
                {where_sql}
                GROUP BY period
                ORDER BY period
            """
        elif plan.aggregation_type == "count_group":
            group_col = plan.group_by or "from_address"
            sql = f"""
                SELECT
                    {group_col} as label,
                    COUNT(*) as count
                FROM emails
                {where_sql}
                GROUP BY {group_col}
                ORDER BY count DESC
                LIMIT 50
            """
        else:
            sql = f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN has_attachments THEN 1 END) as with_attachments,
                    COUNT(DISTINCT from_address) as unique_senders,
                    MIN(date_utc) as earliest,
                    MAX(date_utc) as latest
                FROM emails
                {where_sql}
            """

        return self._db.aggregate_query(sql, params if params else None)

    def get_full_email(self, message_id: str) -> dict[str, Any] | None:
        return self._db.get_email_by_id(message_id)

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return self._db.get_thread(thread_id)

    def get_paginated(self, plan: QueryPlan, page: int, page_size: int) -> PaginatedResult:
        return self._db.search_filtered(
            where_clauses=plan.sql_filters if plan.sql_filters else None,
            params=plan.sql_params if plan.sql_params else None,
            order_by=plan.sort_clause,
            page=page,
            page_size=page_size,
        )

    def get_archive_stats(self) -> dict[str, Any]:
        return self._db.get_archive_stats()

    def export_csv(self, plan: QueryPlan) -> str:
        return self._db.export_filtered_csv(
            where_clauses=plan.sql_filters if plan.sql_filters else None,
            params=plan.sql_params if plan.sql_params else None,
        )
