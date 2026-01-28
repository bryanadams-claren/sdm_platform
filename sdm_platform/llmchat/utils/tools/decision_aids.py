"""Decision aid tools for displaying visual content during conversations."""

import re
from urllib.parse import parse_qs
from urllib.parse import urlparse

from langchain_core.tools import tool


def _convert_to_embed_url(url: str) -> str:
    """
    Convert YouTube/Vimeo watch URLs to embed URLs.

    Args:
        url: Original video URL

    Returns:
        Embed-ready URL for use in iframes
    """
    if not url:
        return url

    parsed = urlparse(url)

    # YouTube: youtube.com/watch?v=VIDEO_ID or youtu.be/VIDEO_ID
    if "youtube.com" in parsed.netloc and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"
    elif "youtu.be" in parsed.netloc:
        video_id = parsed.path.lstrip("/").split("?")[0]
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"

    # Vimeo URLs like vimeo.com/123456789
    if "vimeo.com" in parsed.netloc and "/video/" not in parsed.path:
        # Extract video ID from path like /123456789
        match = re.match(r"/(\d+)", parsed.path)
        if match:
            return f"https://player.vimeo.com/video/{match.group(1)}"

    # Already an embed URL or unknown format - return as-is
    return url


@tool
def show_decision_aid(aid_slug: str, context_message: str = "") -> dict:
    """
    Display a visual aid (image, video, diagram) to help explain a concept.

    Use this tool to show the patient visual content that helps them understand
    medical concepts, procedures, or treatment options.

    Args:
        aid_slug: The slug identifier of the decision aid to display.
        context_message: Optional brief message to accompany the visual aid.

    Returns:
        A dict with aid metadata if successful, or an error message if not found.

    When to use this tool:
    - Explaining anatomy or medical concepts that benefit from visuals
    - Showing what happens during a surgical procedure
    - Demonstrating physical therapy exercises or treatments
    - Comparing healthy vs. affected anatomy

    When NOT to use this tool:
    - Multiple times in the same response (show one aid at a time)
    - For topics where you've already shown an aid in this conversation
    - When the patient hasn't asked about or isn't discussing the topic
    """
    from sdm_platform.journeys.models import DecisionAid  # noqa: PLC0415

    try:
        aid = DecisionAid.objects.get(slug=aid_slug, is_active=True)

        # Convert external video URLs to embed format
        url = aid.media_url
        if aid.aid_type == DecisionAid.AidType.EXTERNAL_VIDEO:
            url = _convert_to_embed_url(url)

        return {
            "success": True,
            "aid_id": str(aid.id),
            "aid_slug": aid.slug,
            "aid_type": aid.aid_type,
            "title": aid.title,
            "url": url,
            "thumbnail_url": aid.thumbnail.url if aid.thumbnail else None,
            "alt_text": aid.alt_text or aid.title,
            "context_message": context_message,
        }
    except DecisionAid.DoesNotExist:
        return {
            "success": False,
            "error": f"Decision aid '{aid_slug}' not found or not active",
        }
