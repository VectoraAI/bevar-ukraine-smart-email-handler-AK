from __future__ import annotations

import json

from src.config.logging import get_logger
from src.llm.client import get_bedrock_client, get_model_id, is_llm_available
from src.models.agents import IntentType, QueryIntent, SortOrder
from src.privacy.audit import safe_log_query

logger = get_logger(module="intent_agent")

_SYSTEM_PROMPT = """You are the Intent Analysis Agent for Bevar Ukraine's email archive system.
Your job: analyze the user's natural language query and extract structured intent.

You MUST respond with valid JSON matching this schema:
{
  "intent_type": "search_emails|aggregate_stats|trend_analysis|specific_email|thread_view|export|general_question",
  "keywords": ["list", "of", "keywords"],
  "from_filter": ["sender@email.com"],
  "to_filter": ["recipient@email.com"],
  "date_from": "YYYY-MM-DD or null",
  "date_to": "YYYY-MM-DD or null",
  "has_attachments": true/false/null,
  "subject_filter": "string or null",
  "language_filter": "string or null",
  "message_id_filter": "string or null",
  "sort_order": "date_desc|date_asc|relevance",
  "limit": null,
  "needs_clarification": false,
  "clarification_questions": [],
  "confidence": 0.0-1.0
}

Rules:
- ONLY analyze queries about the email archive. If the query is unrelated, set intent_type to "general_question" and needs_clarification to true.
- Do NOT invent date ranges or filters the user didn't mention. Only set date_from/date_to if explicitly stated.
- If the query is too vague to produce useful results (e.g., just "emails"), set needs_clarification to true and provide 1-3 clarification questions.
- For statistical/aggregate queries (counts, top senders, trends), use "aggregate_stats" or "trend_analysis".
- For searching specific emails, use "search_emails".
- Extract email addresses, names, and keywords carefully.

CRITICAL rules for "limit":
- When user asks for "the last email", "latest email", "последнее письмо", "newest email", "first email", etc. — set limit to 1 (or the number they specify, e.g., "last 5 emails" → limit=5).
- When user says "last 10", "покажи 3 письма", etc. — set limit to that number.
- When not specified, set limit to null.

CRITICAL rules for "keywords":
- keywords are ONLY for full-text search in email content (subject, body, sender).
- Do NOT put navigational words like "последнее", "покажи", "show", "latest", "newest", "first", "контент", "цепочка", "thread", "переписка" into keywords.
- Only put actual search terms that should match email text: names, topics, organizations, email addresses.
- If the user just wants to browse/navigate (e.g., "show last email", "покажи последнее письмо"), set keywords to an EMPTY list [].

CRITICAL rules for "intent_type":
- "thread_view" — when user asks for a thread/chain/conversation/цепочка/переписка/ланцюжок. Examples: "покажи цепочку последнего письма", "show thread of the last email", "вся переписка с...". The system will automatically find the anchor email first and then load the full thread.
- "search_emails" — searching/browsing emails
- "specific_email" — viewing a single specific email by ID or unique identifier
- "aggregate_stats" — counts, top senders, statistics
- "trend_analysis" — trends over time

CRITICAL rules for sort_order:
- "last/latest/newest/последнее/останнє" → sort_order = "date_desc"
- "first/oldest/earliest/первое/перше" → sort_order = "date_asc"

Respond ONLY with the JSON object, no extra text."""


def analyze_intent(user_query: str, conversation_history: list[dict[str, str]] | None = None) -> QueryIntent:
    """Analyze user query to extract structured intent."""
    logger.info("intent_analysis_start", query=safe_log_query(user_query))

    if not is_llm_available():
        return _fallback_intent(user_query)

    client = get_bedrock_client()

    messages: list[dict[str, str]] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_query})

    try:
        response = client.messages.create(
            model=get_model_id(),
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,  # type: ignore[arg-type]
        )
        content = response.content[0].text  # type: ignore[union-attr]
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]

        data = json.loads(content)
        intent = QueryIntent(raw_query=user_query, **data)
        logger.info("intent_analysis_done", intent_type=intent.intent_type, confidence=intent.confidence)
        return intent

    except Exception as e:
        logger.warning("intent_llm_fallback", error=str(e))
        return _fallback_intent(user_query)


def _fallback_intent(query: str) -> QueryIntent:
    """Simple rule-based fallback when LLM is unavailable."""
    query_lower = query.lower()

    intent_type = IntentType.SEARCH_EMAILS
    stat_keywords = ["сколько", "количество", "count", "how many", "топ", "top", "статистика", "statistics"]
    trend_keywords = ["динамика", "trend", "по месяцам", "по годам", "over time", "timeline"]

    for kw in stat_keywords:
        if kw in query_lower:
            intent_type = IntentType.AGGREGATE_STATS
            break
    for kw in trend_keywords:
        if kw in query_lower:
            intent_type = IntentType.TREND_ANALYSIS
            break

    words = query.split()
    keywords = [w for w in words if len(w) > 2 and "@" not in w]

    from_filter: list[str] = []
    for w in words:
        if "@" in w:
            from_filter.append(w.lower().strip("\"'<>,"))

    return QueryIntent(
        intent_type=intent_type,
        keywords=keywords[:10],
        from_filter=from_filter,
        sort_order=SortOrder.DATE_DESC,
        raw_query=query,
        confidence=0.5,
    )
