"""Worker-owned turn completion. Dash polling only reads the published result."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from ui.jobs import Job


@dataclass(frozen=True)
class TurnRequest:
    thread_id: str
    user_id: int | str | None
    transcript: dict[str, Any]
    input_obj: Any


def finish_transcript(request: TurnRequest, job: Job,
                      commit: Callable[[dict, dict], dict]) -> dict:
    chat = deepcopy(request.transcript)
    chat["thread_id"] = request.thread_id
    chat["_job_id"] = job.id
    chat["_running"] = False
    chat.pop("_save_failed", None)
    chat.pop("pending_clarification_answer", None)
    chat["awaiting_clarification"] = False
    chat["followups"] = []
    if job.cancelled:
        # Unverified model tokens never become a saved analytical answer.
        message = {"type": "AIMessage", "content": "Stopped. You can try another question."}
    elif job.error:
        message = {"type": "AIMessage", "content": "Something went wrong while answering. Please try again."}
    elif job.interrupt is not None:
        chat["awaiting_clarification"] = True
        message = {"type": "ClarifyCard", "payload": job.interrupt}
    else:
        return commit(chat, job.state)
    chat.setdefault("messages", []).append(message)
    return chat


def finalize_turn(request: TurnRequest, job: Job, *, commit: Callable,
                  persist: Callable[[Any, str, dict], Any]) -> None:
    transcript = finish_transcript(request, job, commit)
    # Retain the finished answer even if storage fails. The browser must explain
    # that it is unsaved instead of silently losing the result.
    job.transcript = transcript
    if request.user_id is not None:
        try:
            saved = persist(request.user_id, request.thread_id, transcript)
            if saved is False:
                raise RuntimeError("Conversation storage is unavailable")
        except Exception:
            transcript["_save_failed"] = True
            transcript.setdefault("messages", []).append({"type": "AIMessage", "content":
                "This answer could not be saved. Copy anything you need before leaving this chat, then try again."})
            raise
