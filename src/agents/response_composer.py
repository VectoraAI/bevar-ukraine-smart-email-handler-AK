from __future__ import annotations

import json
from typing import Any

from src.config.logging import get_logger
from src.llm.client import get_bedrock_client, get_model_id, is_llm_available
from src.models.agents import AggregationResult, SearchResult

logger = get_logger(module="response_composer")

_SYSTEM_PROMPT = """You are the Response Composer for Bevar Ukraine's internal email archive tool.
You write the accompanying text for search results and statistics.

Your tone:
- Professional and concise — you are a data analyst for Bevar Ukraine, a Danish-Ukrainian NGO
- Focus on facts: who sent, when, subject, key content
- No filler, no excessive warmth, no emojis

LANGUAGE RULES (CRITICAL):
- If the user writes in Russian → respond in UKRAINIAN (завжди українською)
- If the user writes in Ukrainian → respond in Ukrainian
- If the user writes in English → respond in English
- If the user writes in Danish → respond in Danish

Structure your response:
1. Direct answer to what was asked (1-2 sentences)
2. Key details from the actual email data (sender, date, subject, snippet)
3. Brief observation if useful

Rules:
- NEVER invent data. Only describe what's in the actual results.
- When showing email details, include: sender, date, subject, and first lines of content.
- If nothing was found, say so briefly and suggest how to adjust the query.
- Keep it under 150 words.
- Do NOT include HTML or markdown tables — those are handled separately.
- Do NOT use emojis."""


def compose_response(
    user_query: str,
    search_result: SearchResult | None = None,
    aggregation: AggregationResult | None = None,
    archive_stats: dict[str, Any] | None = None,
) -> str:
    """Compose warm, human response text."""

    context_parts: list[str] = []
    if search_result:
        context_parts.append(
            f"Search returned {search_result.total_count} emails in {search_result.query_time_ms:.0f}ms."
        )
        if search_result.emails:
            # For small result sets, include full details
            sample = search_result.emails[:5]
            for i, e in enumerate(sample, 1):
                parts = [f"Email {i}:"]
                if e.get("from_name") or e.get("from_address"):
                    parts.append(f"  From: {e.get('from_name', '')} <{e.get('from_address', '')}>")
                if e.get("date_utc"):
                    parts.append(f"  Date: {e['date_utc']}")
                if e.get("subject"):
                    parts.append(f"  Subject: {e['subject']}")
                if e.get("snippet"):
                    parts.append(f"  Content preview: {e['snippet']}")
                context_parts.append("\n".join(parts))

    if aggregation:
        if aggregation.summary:
            context_parts.append(f"Summary stats: {json.dumps(aggregation.summary, default=str)}")
        if aggregation.labels and aggregation.values:
            top_items = list(zip(aggregation.labels[:5], aggregation.values[:5]))
            context_parts.append(f"Top results: {top_items}")
        if aggregation.title:
            context_parts.append(f"Chart: {aggregation.title}")

    if archive_stats:
        context_parts.append(f"Archive overview: {json.dumps(archive_stats, default=str)}")

    context = "\n".join(context_parts) if context_parts else "No results found."

    if not is_llm_available():
        return _fallback_response(user_query, search_result, aggregation)

    client = get_bedrock_client()

    try:
        response = client.messages.create(
            model=get_model_id(),
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f'User query: "{user_query}"\n\nActual results:\n{context}',
                }
            ],
        )
        return response.content[0].text  # type: ignore[union-attr]
    except Exception as e:
        logger.warning("composer_llm_error", error=str(e))
        return _fallback_response(user_query, search_result, aggregation)


def _fallback_response(
    query: str,
    search_result: SearchResult | None = None,
    aggregation: AggregationResult | None = None,
) -> str:
    if search_result and search_result.total_count > 0:
        return (
            f"Here are the results for your query. "
            f"Found {search_result.total_count} emails "
            f"in {search_result.query_time_ms:.0f}ms. "
            f"You can use the table below to browse, sort, and filter the results."
        )

    if aggregation and (aggregation.data or aggregation.summary):
        return (
            "Here's the analysis for your query. "
            "The chart and table below show the breakdown. "
            "Feel free to ask follow-up questions to dig deeper."
        )

    return (
        "I couldn't find any emails matching your query in the archive. "
        "Try broadening your search — for example, use fewer keywords, "
        "remove date filters, or check the spelling of names."
    )
