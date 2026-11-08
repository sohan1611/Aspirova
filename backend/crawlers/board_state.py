"""Board-level evidence, independent of ingestion health and coverage."""

from typing import Any


def board_outcome(adapter: object) -> dict[str, Any]:
    """Uninstrumented or interrupted fetches never count as board death."""
    return {
        "board_state": getattr(adapter, "last_board_state", "error"),
        "http_status": getattr(adapter, "last_http_status", None),
    }
