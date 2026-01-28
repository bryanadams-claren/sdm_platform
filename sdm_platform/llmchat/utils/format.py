import datetime


def format_message(  # noqa: PLR0913
    role: str,
    name: str,
    message: str,
    timestamp: datetime.datetime,
    citations: list,
    decision_aids: list | None = None,
):
    """
    Format a message for the frontend.

    Args:
        role: Message role (assistant, ai, bot, human, user, etc.)
        name: Sender name
        message: Message content
        timestamp: Message timestamp
        citations: List of citation dicts from RAG
        decision_aids: Optional list of decision aid dicts to display

    Returns:
        Dict formatted for frontend consumption
    """
    # -- the javascript is looking for one of
    # user (the user) bot (llm) or peer (a different user)
    if role in ["assistant", "ai", "bot"]:
        role = "bot"
    elif role in ["human", "user"]:
        role = "user"
    else:
        role = "unknown"

    result = {
        "role": role,
        "content": message,
        "timestamp": timestamp.isoformat(),
        "name": name,
        "citations": citations,
    }

    if decision_aids:
        result["decision_aids"] = decision_aids

    return result
