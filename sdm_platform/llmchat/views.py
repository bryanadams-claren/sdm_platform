import datetime
import json
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from langchain_core.runnables import RunnableConfig

from sdm_platform.utils.permissions import can_access_conversation
from sdm_platform.utils.responses import json_error
from sdm_platform.utils.responses import json_success

from .models import Conversation
from .utils.chat_history import get_chat_history
from .utils.format import format_message
from .utils.graphs import get_compiled_graph
from .utils.graphs import get_postgres_checkpointer

_CONVERSATION_NOT_FOUND = "Conversation not found"


@login_required
@ensure_csrf_cookie
def conversation(request, conv_id=None):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            Conversation.objects.create(
                user=request.user,
                conv_id=conv_id,
                title=data["title"],
                thread_id=f"chat_{request.user}_{conv_id}".replace("@", "_at_"),
            )
            return json_success()
        except json.JSONDecodeError:
            return json_error("Invalid JSON")
    else:
        # For admins viewing a specific conversation, show that conversation
        if conv_id and request.user.is_staff:
            conv = Conversation.objects.filter(conv_id=conv_id).first()
            if conv:
                conversations = Conversation.objects.filter(user=conv.user).order_by(
                    "-created_at",
                )
                return render(
                    request,
                    "llmchat/conversation.html",
                    {
                        "conversations": conversations,
                        "active_conv_id": conv_id,
                        "conversation_owner": conv.user,
                    },
                )
            raise Http404(_CONVERSATION_NOT_FOUND)

        # Check access for non-admin users viewing a specific conversation
        if conv_id and not can_access_conversation(request.user, conv_id):
            raise Http404(_CONVERSATION_NOT_FOUND)

        conversations = Conversation.objects.filter(user=request.user).order_by(
            "-created_at",
        )
        if not conversations:
            conv_id = settings.DEFAULT_CONV_ID
            Conversation.objects.create(
                user=request.user,
                conv_id=settings.DEFAULT_CONV_ID,
                title="General Q&A",
                thread_id=f"chat_{request.user}_{conv_id}".replace("@", "_at_"),
            )
            conversations = Conversation.objects.filter(user=request.user).order_by(
                "-created_at",
            )
        if not conv_id:
            conv_id = conversations[0].conv_id
        return render(
            request,
            "llmchat/conversation.html",
            {"conversations": conversations, "active_conv_id": conv_id},
        )


def _get_name(msg):
    mtype = msg.get("type", None)
    if mtype == "ai":
        return settings.AI_ASSISTANT_NAME
    # ...otherwise ...
    return msg.get("data", {}).get("metadata", {}).get("username", "UnknownName")


@login_required
def history(request, conv_id):
    # Check access permissions
    if not can_access_conversation(request.user, conv_id):
        raise Http404(_CONVERSATION_NOT_FOUND)

    # For admins, get the thread_id from the actual conversation owner
    if request.user.is_staff:
        conv = Conversation.objects.filter(conv_id=conv_id).first()
        if not conv:
            raise Http404(_CONVERSATION_NOT_FOUND)
        thread_id = conv.thread_id
    else:
        thread_id = f"chat_{request.user}_{conv_id}".replace("@", "_at_")

    config = RunnableConfig(configurable={"thread_id": thread_id})
    # you can also build a dict, like {"configurable": {"thread_id": thread_id}}

    data = {}
    with get_postgres_checkpointer() as checkpointer:
        graph = get_compiled_graph(checkpointer)
        full_history = list(graph.get_state_history(config=config))
        chat_history = get_chat_history(full_history)
        msg_list = []
        for turn in chat_history:
            msg_list += [
                format_message(
                    msg.get("type", None),
                    _get_name(msg),
                    msg.get("data", {}).get("content", ""),
                    turn.get(
                        "created_at",
                        datetime.datetime.now(ZoneInfo(settings.TIME_ZONE)),
                    ),
                    turn.get("turn_citations", []),
                )
                for msg in turn["new_messages"]
                if msg.get("type", None) in ["human", "ai"]
            ]
        data.update({"messages": msg_list})
    return JsonResponse(data)
