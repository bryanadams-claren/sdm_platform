from datetime import datetime

from langchain_core.messages import message_to_dict


def get_chat_history(history):
    """
    Turn a list of StateSnapshots into per-step diffs.
    Each entry only contains the messages that were added at that step.
    """
    # Put into chronological order (oldest → newest)
    snaps = list(reversed(history))

    prev_msgs = []
    diffs = []
    i = 1
    for snap in snaps:  # skip that first message (??)
        """
        for posterity, a snap contains:
          snap.config
          snap.metadata
          snap.values
          snap.next
          snap.tasks
          snap.created_at <-- this is the useful one
        """
        cur_msgs = snap.values.get("messages", [])
        # new messages = everything after the previous snapshot's messages
        new_msgs = cur_msgs[len(prev_msgs) :]
        if not new_msgs:
            continue
        diffs.append(
            {
                "created_at": datetime.fromisoformat(snap.created_at),
                "new_messages": [message_to_dict(m) for m in new_msgs],
                "turn_citations": snap.values.get("turn_citations", []),
                "turn_decision_aids": snap.values.get("turn_decision_aids", []),
            },
        )
        prev_msgs = cur_msgs
        i = i + 1
    return diffs
