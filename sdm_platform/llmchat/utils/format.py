import datetime


def format_message(  # noqa: PLR0913
    role: str,
    name: str,
    message: str,
    timestamp: datetime.datetime,
    citations: list,
    video_clips: list,
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
        "video_clips": video_clips,
    }


def format_thread_id(useremail: str, conv_id: str):
    return f"chat_{useremail}_{conv_id}".replace("@", "_at_").replace(" ", "_")
