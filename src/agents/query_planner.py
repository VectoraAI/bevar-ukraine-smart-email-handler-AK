from __future__ import annotations

from src.config.logging import get_logger
from src.models.agents import IntentType, QueryIntent, QueryPlan, SearchMode, SortOrder

logger = get_logger(module="query_planner")


def build_query_plan(intent: QueryIntent) -> QueryPlan:
    """Convert a QueryIntent into an executable QueryPlan against the DuckDB index."""
    logger.info("query_plan_start", intent_type=intent.intent_type)

    filters: list[str] = []
    params: dict[str, str | int | bool] = {}
    param_idx = 1

    if intent.from_filter:
        placeholders = []
        for addr in intent.from_filter:
            key = f"from_{param_idx}"
            placeholders.append(f"LOWER(from_address) LIKE LOWER(${param_idx})")
            params[key] = f"%{addr}%"
            param_idx += 1
        filters.append("(" + " OR ".join(placeholders) + ")")

    if intent.to_filter:
        placeholders = []
        for addr in intent.to_filter:
            key = f"to_{param_idx}"
            placeholders.append(f"to_addresses::VARCHAR ILIKE ${param_idx}")
            params[key] = f"%{addr}%"
            param_idx += 1
        filters.append("(" + " OR ".join(placeholders) + ")")

    if intent.date_from:
        filters.append(f"date_utc >= ${param_idx}")
        params[f"date_from_{param_idx}"] = intent.date_from
        param_idx += 1

    if intent.date_to:
        filters.append(f"date_utc <= ${param_idx}")
        params[f"date_to_{param_idx}"] = intent.date_to
        param_idx += 1

    if intent.has_attachments is not None:
        filters.append(f"has_attachments = ${param_idx}")
        params[f"attach_{param_idx}"] = intent.has_attachments
        param_idx += 1

    if intent.subject_filter:
        filters.append(f"subject ILIKE ${param_idx}")
        params[f"subj_{param_idx}"] = f"%{intent.subject_filter}%"
        param_idx += 1

    if intent.message_id_filter:
        filters.append(f"message_id = ${param_idx}")
        params[f"mid_{param_idx}"] = intent.message_id_filter
        param_idx += 1

    fts_query = ""
    search_mode = SearchMode.LEXICAL
    if intent.keywords:
        fts_query = " ".join(intent.keywords)
        search_mode = SearchMode.LEXICAL

    sort_map = {
        SortOrder.DATE_DESC: "date_utc DESC",
        SortOrder.DATE_ASC: "date_utc ASC",
        SortOrder.RELEVANCE: "score DESC",
    }
    sort_clause = sort_map.get(intent.sort_order, "date_utc DESC")

    needs_agg = intent.intent_type in (IntentType.AGGREGATE_STATS, IntentType.TREND_ANALYSIS)
    agg_type = ""
    group_by = ""
    if intent.intent_type == IntentType.AGGREGATE_STATS:
        agg_type = "count_group"
        group_by = "from_address"
    elif intent.intent_type == IntentType.TREND_ANALYSIS:
        agg_type = "time_series"
        group_by = "month"

    result_limit = intent.limit or 0

    plan = QueryPlan(
        search_mode=search_mode,
        fts_query=fts_query,
        sql_filters=filters,
        sql_params=params,
        needs_aggregation=needs_agg,
        aggregation_type=agg_type,
        group_by=group_by,
        sort_clause=sort_clause,
        result_limit=result_limit,
        intent=intent,
    )

    logger.info("query_plan_built", filters=len(filters), fts=bool(fts_query), aggregation=needs_agg)
    return plan
