from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from finrag.query_runtime import QueryResponse, QueryStatus, ToolTraceEvent


@dataclass
class ConversationState:
    conversation_id: str
    pending_question: str | None = None
    pending_clarifying_question: str | None = None
    updated_at_epoch_s: float = 0.0


class ConversationStore:
    """
    In-memory conversation state for multi-turn clarification flows.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._conversations: dict[str, ConversationState] = {}

    def state(self, conversation_id: str | None) -> ConversationState:
        requested = (conversation_id or "").strip()
        key = requested if requested else str(uuid.uuid4())
        now = time.time()
        with self._lock:
            state = self._conversations.get(key)
            if state is None:
                state = ConversationState(conversation_id=key, updated_at_epoch_s=now)
                self._conversations[key] = state
            else:
                state.updated_at_epoch_s = now
            return state

    def resolve_question(self, *, conversation_id: str | None, question: str) -> tuple[str, str, list[ToolTraceEvent]]:
        state = self.state(conversation_id)
        traces: list[ToolTraceEvent] = []
        effective_question = question

        pending = state.pending_question
        if pending and pending.strip():
            effective_question = f"{pending}\n\nUser clarification:\n{question}"
            traces.append(
                ToolTraceEvent(
                    tool="apply_user_clarification",
                    args={"conversation_id": state.conversation_id},
                    result="Merged pending question with follow-up clarification turn.",
                )
            )
        return effective_question, state.conversation_id, traces

    def update_after_response(
        self,
        *,
        conversation_id: str | None,
        effective_question: str,
        response: QueryResponse,
    ) -> None:
        cid = (conversation_id or "").strip()
        if not cid:
            return

        with self._lock:
            state = self._conversations.get(cid)
            if state is None:
                state = ConversationState(conversation_id=cid)
                self._conversations[cid] = state
            state.updated_at_epoch_s = time.time()
            if response.status == QueryStatus.CLARIFICATION_REQUIRED:
                state.pending_question = effective_question
                state.pending_clarifying_question = response.clarifying_question
                return
            state.pending_question = None
            state.pending_clarifying_question = None

    def clear(self) -> None:
        with self._lock:
            self._conversations.clear()
