from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    SEARCH_EMAILS = "search_emails"
    AGGREGATE_STATS = "aggregate_stats"
    TREND_ANALYSIS = "trend_analysis"
    SPECIFIC_EMAIL = "specific_email"
    THREAD_VIEW = "thread_view"
    EXPORT = "export"
    GENERAL_QUESTION = "general_question"


class SearchMode(str, Enum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SortOrder(str, Enum):
    DATE_ASC = "date_asc"
    DATE_DESC = "date_desc"
    RELEVANCE = "relevance"


class QueryIntent(BaseModel):
    """Output of Intent Agent — structured user intention."""

    intent_type: IntentType
    keywords: list[str] = Field(default_factory=list)
    from_filter: list[str] = Field(default_factory=list)
    to_filter: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    has_attachments: bool | None = None
    subject_filter: str | None = None
    language_filter: str | None = None
    message_id_filter: str | None = None
    sort_order: SortOrder = SortOrder.DATE_DESC
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    raw_query: str = ""
    confidence: float = 1.0


class QueryPlan(BaseModel):
    """Output of Query Planner — executable plan against the index."""

    search_mode: SearchMode = SearchMode.LEXICAL
    fts_query: str = ""
    sql_filters: list[str] = Field(default_factory=list)
    sql_params: dict[str, Any] = Field(default_factory=dict)
    needs_aggregation: bool = False
    aggregation_type: str = ""
    group_by: str = ""
    sort_clause: str = "date_utc DESC"
    intent: QueryIntent | None = None


class SearchResult(BaseModel):
    """Output of Search & Retrieval Agent."""

    emails: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    query_time_ms: float = 0.0
    threads: dict[str, list[str]] = Field(default_factory=dict)


class AggregationResult(BaseModel):
    """Output of Aggregation Agent."""

    title: str = ""
    description: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    chart_type: str = ""
    labels: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class PresentationData(BaseModel):
    """Output of Presentation Agent — ready-to-render artifacts."""

    table_html: str = ""
    chart_configs: list[dict[str, Any]] = Field(default_factory=list)
    stats_cards: list[dict[str, str]] = Field(default_factory=list)
    export_available: bool = False


class FinalResponse(BaseModel):
    """Final assembled response to the user."""

    text: str = ""
    presentation: PresentationData | None = None
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    correlation_id: str = ""
