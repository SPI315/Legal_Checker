from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

def retry_with_backoff(
    operation: Callable[[], T],
    attempts: int = 3,
    base_delay_sec: float = 0.25,
) -> T:
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - exercised through callers
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(base_delay_sec * (2 ** (attempt - 1)))

    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_with_backoff failed without captured exception")
