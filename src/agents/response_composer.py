from __future__ import annotations

import json

from src.config.logging import get_logger
from src.llm.client import get_bedrock_client, get_model_id, is_llm_available
from src.models.agents import AggregationResult, SearchResult

logger = get_logger(module="response_composer")

_SYSTEM_PROMPT = """You are the Response Composer for Bevar Ukraine's internal email archive tool.
You write the accompanying text for search results and statistics.

Your tone:
- Warm, human, professional — you are a team member of Bevar Ukraine, a Danish-Ukrainian NGO
- Detailed but concise — highlight key findings
- Supportive — suggest next steps or filters if useful
- Match the user's language (Russian/Ukrainian/English/Danish)

Structure your response:
1. Brief warm greeting/intro (1-2 sentences)
2. Summary of what was found
3. Key observations (if any patterns stand out)
4. Suggestion for next steps (optional, if relevant)

Rules:
- NEVER invent data. Only describe what's in the actual results.
- If nothing was found, say so warmly and suggest adjusting the query.
- Keep it under 200 words.
- Do NOT include HTML or markdown tables — those are handled separately.
- Do NOT repeat raw data — just summarize and highlight."""


def compose_response(
    user_query: str,
    search_result: SearchResult | None = None,
    aggregation: AggregationResult | None = None,
    archive_stats: dict | None = None,
) -> str:
    """Compose warm, human response text."""

    context_parts: list[str] = []
    if search_result:
        context_parts.append(
            f"Search returned {search_result.total_count} emails in {search_result.query_time_ms:.0f}ms."
        )
        if search_result.emails:
            sample = search_result.emails[:5]
            context_parts.append(f"Sample subjects: {[e.get('subject', '') for e in sample]}")

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
