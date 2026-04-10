from __future__ import annotations

from app.services.orchestration.types import PipelineStatusSnapshot


class InMemoryPipelineStateStore:
    def __init__(self) -> None:
        self._state: dict[str, object] = {}
        self._status: dict[str, PipelineStatusSnapshot] = {}

    def save(self, session_id: str, payload: object) -> None:
        self._state[session_id] = payload

    def get(self, session_id: str) -> object | None:
        return self._state.get(session_id)

    def save_status(self, session_id: str, status: PipelineStatusSnapshot) -> None:
        self._status[session_id] = status

    def get_status(self, session_id: str) -> PipelineStatusSnapshot | None:
        return self._status.get(session_id)
