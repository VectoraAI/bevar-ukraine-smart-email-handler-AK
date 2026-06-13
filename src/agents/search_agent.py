from __future__ import annotations

from src.agents.data_access_agent import DataAccessAgent
from src.config.logging import get_logger
from src.models.agents import QueryPlan, SearchResult

logger = get_logger(module="search_agent")


class SearchAgent:
    def __init__(self, data_access: DataAccessAgent) -> None:
        self._data = data_access

    def search(self, plan: QueryPlan, page: int = 1, page_size: int = 50) -> SearchResult:
        """Execute search and enrich results with thread info."""
        result = self._data.execute_search(plan, page=page, page_size=page_size)
        logger.info(
            "search_complete",
            total=result.total_count,
            returned=len(result.emails),
            time_ms=result.query_time_ms,
        )
        return result

    def get_email_detail(self, message_id: str) -> dict | None:
        return self._data.get_full_email(message_id)

    def get_thread(self, thread_id: str) -> list[dict]:
        return self._data.get_thread(thread_id)
