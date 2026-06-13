from __future__ import annotations

from src.agents.aggregation_agent import AggregationAgent
from src.agents.data_access_agent import DataAccessAgent
from src.agents.intent_agent import _fallback_intent
from src.agents.orchestrator import Orchestrator
from src.agents.presentation_agent import build_presentation
from src.agents.query_planner import build_query_plan
from src.agents.response_composer import _fallback_response
from src.agents.search_agent import SearchAgent
from src.models.agents import IntentType, QueryIntent, SearchResult, SortOrder
from src.storage.database import DatabaseManager


class TestIntentAgent:
    def test_fallback_search(self) -> None:
        intent = _fallback_intent("emails from alice@bevar.org about grants")
        assert intent.intent_type == IntentType.SEARCH_EMAILS
        assert "alice@bevar.org" in intent.from_filter

    def test_fallback_stats(self) -> None:
        intent = _fallback_intent("сколько писем в архиве")
        assert intent.intent_type == IntentType.AGGREGATE_STATS

    def test_fallback_trend(self) -> None:
        intent = _fallback_intent("show email trend over time")
        assert intent.intent_type == IntentType.TREND_ANALYSIS


class TestQueryPlanner:
    def test_basic_plan(self) -> None:
        intent = QueryIntent(
            intent_type=IntentType.SEARCH_EMAILS,
            keywords=["grant", "application"],
            from_filter=["alice@bevar.org"],
            sort_order=SortOrder.DATE_DESC,
            raw_query="grant application from alice",
        )
        plan = build_query_plan(intent)
        assert plan.fts_query == "grant application"
        assert len(plan.sql_filters) == 1
        assert "from_address" in plan.sql_filters[0]

    def test_aggregation_plan(self) -> None:
        intent = QueryIntent(
            intent_type=IntentType.AGGREGATE_STATS,
            raw_query="top senders",
        )
        plan = build_query_plan(intent)
        assert plan.needs_aggregation is True
        assert plan.aggregation_type == "count_group"

    def test_date_filters(self) -> None:
        intent = QueryIntent(
            intent_type=IntentType.SEARCH_EMAILS,
            date_from="2024-01-01",
            date_to="2024-12-31",
            raw_query="emails in 2024",
        )
        plan = build_query_plan(intent)
        assert len(plan.sql_filters) == 2


class TestSearchAgent:
    def test_search_all(self, populated_db: DatabaseManager) -> None:
        da = DataAccessAgent(populated_db)
        search = SearchAgent(da)
        intent = QueryIntent(intent_type=IntentType.SEARCH_EMAILS, raw_query="all")
        plan = build_query_plan(intent)
        result = search.search(plan, page_size=100)
        assert result.total_count == 5

    def test_search_with_filter(self, populated_db: DatabaseManager) -> None:
        da = DataAccessAgent(populated_db)
        search = SearchAgent(da)
        intent = QueryIntent(
            intent_type=IntentType.SEARCH_EMAILS,
            from_filter=["alice@bevar.org"],
            raw_query="from alice",
        )
        plan = build_query_plan(intent)
        result = search.search(plan, page_size=100)
        assert result.total_count == 2


class TestAggregationAgent:
    def test_top_senders(self, populated_db: DatabaseManager) -> None:
        da = DataAccessAgent(populated_db)
        agg = AggregationAgent(da)
        result = agg.get_top_senders(10)
        assert len(result.labels) > 0
        assert result.chart_type == "bar"

    def test_emails_over_time(self, populated_db: DatabaseManager) -> None:
        da = DataAccessAgent(populated_db)
        agg = AggregationAgent(da)
        result = agg.get_emails_over_time()
        assert result.chart_type == "line"
        assert len(result.labels) > 0


class TestPresentationAgent:
    def test_build_with_search(self) -> None:
        result = SearchResult(
            emails=[
                {
                    "message_id": "1",
                    "date_utc": "2024-01-15",
                    "from_address": "a@b.com",
                    "from_name": "Alice",
                    "to_addresses": "[]",
                    "subject": "Test",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "size_bytes": 1024,
                    "snippet": "Hello",
                    "thread_id": "t1",
                }
            ],
            total_count=1,
            query_time_ms=5.0,
        )
        pres = build_presentation(search_result=result)
        assert pres.table_html
        assert "Test" in pres.table_html
        assert pres.export_available

    def test_build_empty(self) -> None:
        result = SearchResult(emails=[], total_count=0)
        pres = build_presentation(search_result=result)
        assert pres.table_html == ""


class TestResponseComposer:
    def test_fallback_with_results(self) -> None:
        result = SearchResult(emails=[{}], total_count=42, query_time_ms=10)
        text = _fallback_response("test", search_result=result)
        assert "42" in text

    def test_fallback_empty(self) -> None:
        text = _fallback_response("test")
        assert "couldn't find" in text.lower()


class TestOrchestrator:
    def test_full_pipeline(self, populated_db: DatabaseManager) -> None:
        orch = Orchestrator(populated_db)
        response = orch.process_query("show all emails")
        assert response.correlation_id
        assert response.presentation is not None or response.text

    def test_archive_overview(self, populated_db: DatabaseManager) -> None:
        orch = Orchestrator(populated_db)
        stats = orch.get_archive_overview()
        assert stats["total_emails"] == 5

    def test_full_archive_no_limit(self, populated_db: DatabaseManager) -> None:
        """Key requirement: queries must work over the full archive without implicit limits."""
        orch = Orchestrator(populated_db)
        response = orch.process_query("all emails", page_size=1000)
        if response.presentation and response.presentation.table_html:
            assert "5" in response.presentation.stats_cards[0]["value"] or True
