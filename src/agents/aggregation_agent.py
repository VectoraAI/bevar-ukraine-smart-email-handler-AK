from __future__ import annotations

from typing import Any

from src.agents.data_access_agent import DataAccessAgent
from src.config.logging import get_logger
from src.models.agents import AggregationResult, QueryPlan

logger = get_logger(module="aggregation_agent")


class AggregationAgent:
    def __init__(self, data_access: DataAccessAgent) -> None:
        self._data = data_access

    def aggregate(self, plan: QueryPlan) -> AggregationResult:
        """Run aggregation based on the query plan."""
        raw_data = self._data.execute_aggregation(plan)
        intent = plan.intent

        if plan.aggregation_type == "contacts":
            return self._build_contacts(raw_data, intent)
        elif plan.aggregation_type == "time_series":
            return self._build_time_series(raw_data, intent)
        elif plan.aggregation_type == "count_group":
            return self._build_grouped_count(raw_data, intent, plan.group_by)
        else:
            return self._build_summary(raw_data, intent)

    def get_top_senders(self, limit: int = 20) -> AggregationResult:
        data = self._data._db.aggregate_query(
            "SELECT from_address as label, COUNT(*) as count FROM emails "
            "GROUP BY from_address ORDER BY count DESC LIMIT $1",
            [limit],
        )
        return AggregationResult(
            title="Top Senders",
            chart_type="bar",
            labels=[r["label"] for r in data],
            values=[float(r["count"]) for r in data],
            data=data,
        )

    def get_top_recipients(self, limit: int = 20) -> AggregationResult:
        data = self._data._db.aggregate_query(
            """
            SELECT UNNEST(from_json_strict(to_addresses, '["VARCHAR"]')) as label,
                   COUNT(*) as count
            FROM emails
            GROUP BY label ORDER BY count DESC LIMIT $1
            """,
            [limit],
        )
        return AggregationResult(
            title="Top Recipients",
            chart_type="bar",
            labels=[r["label"] for r in data],
            values=[float(r["count"]) for r in data],
            data=data,
        )

    def get_emails_over_time(self) -> AggregationResult:
        data = self._data._db.aggregate_query(
            """
            SELECT STRFTIME(date_utc, '%Y-%m') as period, COUNT(*) as count
            FROM emails WHERE date_utc IS NOT NULL
            GROUP BY period ORDER BY period
            """
        )
        return AggregationResult(
            title="Emails Over Time",
            chart_type="line",
            labels=[r["period"] for r in data],
            values=[float(r["count"]) for r in data],
            data=data,
        )

    def get_attachment_stats(self) -> AggregationResult:
        data = self._data._db.aggregate_query(
            """
            SELECT
                CASE WHEN has_attachments THEN 'With Attachments' ELSE 'Without Attachments' END as label,
                COUNT(*) as count
            FROM emails GROUP BY has_attachments
            """
        )
        return AggregationResult(
            title="Attachment Distribution",
            chart_type="doughnut",
            labels=[r["label"] for r in data],
            values=[float(r["count"]) for r in data],
            data=data,
        )

    def _build_time_series(self, raw_data: list[dict[str, Any]], intent: Any) -> AggregationResult:
        return AggregationResult(
            title="Email Volume Over Time",
            description=f"Time series for query: {intent.raw_query if intent else ''}",
            chart_type="line",
            labels=[r.get("period", "") for r in raw_data],
            values=[float(r.get("count", 0)) for r in raw_data],
            data=raw_data,
        )

    def _build_grouped_count(self, raw_data: list[dict[str, Any]], intent: Any, group_by: str) -> AggregationResult:
        return AggregationResult(
            title=f"Distribution by {group_by}",
            description=f"Grouped count for query: {intent.raw_query if intent else ''}",
            chart_type="bar",
            labels=[str(r.get("label", "")) for r in raw_data],
            values=[float(r.get("count", 0)) for r in raw_data],
            data=raw_data,
        )

    def _build_contacts(self, raw_data: list[dict[str, Any]], intent: Any) -> AggregationResult:
        return AggregationResult(
            title="Contacts from Email Archive",
            description=f"Unique contacts extracted from archive: {intent.raw_query if intent else ''}",
            data=raw_data,
            summary={"total_contacts": len(raw_data)},
        )

    def _build_summary(self, raw_data: list[dict[str, Any]], intent: Any) -> AggregationResult:
        summary: dict[str, Any] = raw_data[0] if raw_data else {}
        return AggregationResult(
            title="Archive Summary",
            description=f"Summary for query: {intent.raw_query if intent else ''}",
            summary=summary,
            data=raw_data,
        )
