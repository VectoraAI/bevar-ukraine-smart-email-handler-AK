from __future__ import annotations

from src.config.logging import get_logger
from src.llm.client import get_bedrock_client, get_model_id, is_llm_available
from src.models.agents import QueryIntent

logger = get_logger(module="clarification_agent")

_SYSTEM_PROMPT = """You are the Clarification Agent for Bevar Ukraine's email archive system.
Your role: formulate warm, concise clarification questions when the user's query is too vague.

Rules:
- Ask 1-3 specific questions, no more.
- Be warm, professional, and helpful — you are a member of the Bevar Ukraine team.
- Ask in the same language the user used.
- Focus on what would most help narrow the search: specific person, time period, topic, etc.
- Do NOT be generic. Tailor questions to what the user seems to want.
- Return ONLY the questions as a JSON array of strings, e.g. ["Question 1?", "Question 2?"]"""


def generate_clarification(intent: QueryIntent) -> list[str]:
    """Generate warm clarification questions based on incomplete intent."""
    if not is_llm_available():
        return _fallback_clarification(intent)

    client = get_bedrock_client()

    user_msg = f"""User query: "{intent.raw_query}"

The system determined these aspects need clarification:
- Intent type detected: {intent.intent_type}
- Current filters: from={intent.from_filter}, to={intent.to_filter}, dates={intent.date_from}-{intent.date_to}
- Keywords: {intent.keywords}
- Pre-generated questions (may use or improve): {intent.clarification_questions}

Generate 1-3 warm, specific clarification questions."""

    try:
        response = client.messages.create(
            model=get_model_id(),
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        import json

        content = response.content[0].text.strip()  # type: ignore[union-attr]
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        questions = json.loads(content)
        if isinstance(questions, list):
            return questions[:3]
    except Exception as e:
        logger.warning("clarification_llm_error", error=str(e))

    return _fallback_clarification(intent)


def _fallback_clarification(intent: QueryIntent) -> list[str]:
    if intent.clarification_questions:
        return intent.clarification_questions[:3]
    return [
        "Could you specify what exactly you're looking for in the email archive? "
        "For example: emails from a specific person, about a particular topic, or within a date range?"
    ]
