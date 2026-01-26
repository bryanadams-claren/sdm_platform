import datetime


def format_message(
    role: str,
    name: str,
    message: str,
    timestamp: datetime.datetime,
    citations: list,
):
    # -- the javascript is looking for one of
    # user (the user) bot (llm) or peer (a different user)
    if role in ["assistant", "ai", "bot"]:
        role = "bot"
    elif role in ["human", "user"]:
        role = "user"
    else:
        role = "unknown"

    return {
        "role": role,
        "content": message,
        "timestamp": timestamp.isoformat(),
        "name": name,
        "citations": citations,
    }
