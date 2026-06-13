from __future__ import annotations

import uuid
from typing import Any

from src.agents.aggregation_agent import AggregationAgent
from src.agents.clarification_agent import generate_clarification
from src.agents.data_access_agent import DataAccessAgent
from src.agents.intent_agent import analyze_intent
from src.agents.presentation_agent import build_presentation
from src.agents.query_planner import build_query_plan
from src.agents.response_composer import compose_response
from src.agents.search_agent import SearchAgent
from src.config.logging import get_logger
from src.models.agents import (
    AggregationResult,
    FinalResponse,
    IntentType,
    QueryPlan,
    SearchResult,
)
from src.privacy.audit import safe_log_query
from src.storage.database import DatabaseManager

logger = get_logger(module="orchestrator")


class Orchestrator:
    """Central coordinator for the multi-agent pipeline."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._data_access = DataAccessAgent(db)
        self._search = SearchAgent(self._data_access)
        self._aggregation = AggregationAgent(self._data_access)
        self._sessions: dict[str, list[dict[str, str]]] = {}

    def process_query(
        self,
        user_query: str,
        session_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
        user_id: str = "anonymous",
        ip_address: str = "",
    ) -> FinalResponse:
        """Main entry point: process a user query through the agent pipeline."""
        correlation_id = str(uuid.uuid4())[:8]
        if not session_id:
            session_id = str(uuid.uuid4())

        logger.info(
            "query_start",
            correlation_id=correlation_id,
            query=safe_log_query(user_query),
            session_id=session_id,
        )

        history = self._sessions.get(session_id, [])

        # 1. Intent Agent
        intent = analyze_intent(user_query, conversation_history=history if history else None)
        intent.raw_query = user_query

        # 2. Guard: reject out-of-domain (but be lenient)
        if intent.intent_type == IntentType.GENERAL_QUESTION and not intent.keywords:
            # Re-check: if query mentions emails/archive/letters, treat as search
            query_lower = user_query.lower()
            archive_words = [
                "письм",
                "email",
                "mail",
                "архив",
                "archive",
                "контакт",
                "contact",
                "отправ",
                "send",
                "получ",
                "receiv",
                "переписк",
                "скачать",
                "export",
                "xlsx",
                "csv",
                "таблиц",
                "table",
            ]
            if any(w in query_lower for w in archive_words):
                intent.intent_type = IntentType.SEARCH_EMAILS
                intent.confidence = 0.5
                logger.info("intent_override", from_type="general_question", to_type="search_emails")
            else:
                return FinalResponse(
                    text="I can only help with questions about the Bevar Ukraine email archive. "
                    "Please ask about emails, senders, topics, or statistics from our mailbox.",
                    correlation_id=correlation_id,
                )

        # 3. Clarification if needed
        if intent.needs_clarification:
            questions = generate_clarification(intent)
            self._save_to_history(session_id, user_query, "assistant_clarification")
            return FinalResponse(
                text="",
                needs_clarification=True,
                clarification_questions=questions,
                correlation_id=correlation_id,
            )

        # 4. Query Planner
        plan = build_query_plan(intent)

        # 5. Execute search/aggregation (with multi-step support)
        search_result: SearchResult | None = None
        aggregation: AggregationResult | None = None

        effective_page_size = plan.result_limit if plan.result_limit > 0 else page_size

        if intent.intent_type == IntentType.THREAD_VIEW:
            # Multi-step: find anchor email(s), then load full thread
            search_result = self._resolve_thread_view(plan, page, effective_page_size)
            logger.info("thread_view_done", total=search_result.total_count)
        elif plan.needs_aggregation:
            aggregation = self._aggregation.aggregate(plan)
            logger.info("aggregation_done", type=plan.aggregation_type, data_points=len(aggregation.data))
        else:
            search_result = self._search.search(plan, page=page, page_size=effective_page_size)
            logger.info("search_done", total=search_result.total_count)

        # 6. Presentation
        total_pages = 1
        if search_result:
            total_pages = max(1, (search_result.total_count + effective_page_size - 1) // effective_page_size)
        presentation = build_presentation(
            search_result=search_result,
            aggregation=aggregation,
            page=page,
            page_size=max(effective_page_size, search_result.total_count if search_result else 0),
            total_pages=total_pages,
        )

        # 7. Response Composer
        text = compose_response(
            user_query,
            search_result=search_result,
            aggregation=aggregation,
            archive_stats=self._data_access.get_archive_stats(),
        )

        # 8. Audit log
        result_count = search_result.total_count if search_result else len(aggregation.data) if aggregation else 0
        self._db.log_audit(user_id, "query", user_query, result_count, ip_address)

        # Save conversation history
        self._save_to_history(session_id, user_query, "user")

        final = FinalResponse(
            text=text,
            presentation=presentation,
            correlation_id=correlation_id,
        )

        logger.info("query_complete", correlation_id=correlation_id)
        return final

    def get_email_detail(self, message_id: str) -> dict[str, Any] | None:
        return self._search.get_email_detail(message_id)

    def get_thread(self, thread_id: str) -> list[dict[str, Any]]:
        return self._search.get_thread(thread_id)

    def get_archive_overview(self) -> dict[str, Any]:
        return self._data_access.get_archive_stats()

    def export_csv(self, user_query: str) -> str:
        intent = analyze_intent(user_query)
        plan = build_query_plan(intent)
        return self._data_access.export_csv(plan)

    def get_top_senders(self, limit: int = 20) -> AggregationResult:
        return self._aggregation.get_top_senders(limit)

    def get_emails_over_time(self) -> AggregationResult:
        return self._aggregation.get_emails_over_time()

    def _resolve_thread_view(self, plan: QueryPlan, page: int, page_size: int) -> SearchResult:
        """Multi-step: find anchor email, then load full thread."""
        import time

        start = time.monotonic()

        # Step 1: Find the anchor email (e.g., the latest email matching filters)
        anchor_result = self._search.search(plan, page=1, page_size=1)

        if not anchor_result.emails:
            return anchor_result

        anchor = anchor_result.emails[0]
        thread_id = anchor.get("thread_id", "")

        if not thread_id:
            # No thread — return just this email
            return anchor_result

        # Step 2: Load the full thread
        logger.info("thread_resolve", thread_id=thread_id)
        thread_emails = self._data_access.get_thread(thread_id)
        elapsed = (time.monotonic() - start) * 1000

        # Convert full email dicts to search-result format (with snippets)
        emails: list[dict[str, Any]] = []
        for e in thread_emails:
            emails.append(
                {
                    "message_id": e.get("message_id", ""),
                    "date_utc": e.get("date_utc"),
                    "from_address": e.get("from_address", ""),
                    "from_name": e.get("from_name", ""),
                    "to_addresses": e.get("to_addresses", ""),
                    "subject": e.get("subject", ""),
                    "has_attachments": e.get("has_attachments", False),
                    "attachment_count": e.get("attachment_count", 0),
                    "size_bytes": e.get("size_bytes", 0),
                    "thread_id": e.get("thread_id", ""),
                    "snippet": (e.get("body_text") or "")[:200],
                }
            )

        return SearchResult(
            emails=emails,
            total_count=len(emails),
            query_time_ms=elapsed,
        )

    def _save_to_history(self, session_id: str, content: str, role: str) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append({"role": role, "content": content})
        if len(self._sessions[session_id]) > 20:
            self._sessions[session_id] = self._sessions[session_id][-20:]
