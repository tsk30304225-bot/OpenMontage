"""Load the compiled visual_timeline and check that it can be executed.

``edit_decisions.visual_timeline`` is either the compiled object or a path to
its JSON. Every render path reads it the same way; callers keep their own
error wording (tests and agents rely on it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def missing_timeline_file(value: Any) -> str | None:
    """Error message when ``value`` names a timeline file that does not exist."""
    if isinstance(value, str) and not Path(value).is_file():
        return f"edit_decisions.visual_timeline file not found: {Path(value)}"
    return None


def read_timeline(value: Any) -> Any:
    """The timeline object: a path string is parsed as JSON, anything else passes through.

    OSError / ValueError from reading or parsing propagate to the caller.
    """
    if isinstance(value, str):
        return json.loads(Path(value).read_text(encoding="utf-8"))
    return value


def unresolved_anchors_error(timeline: dict[str, Any]) -> str | None:
    """Error message when some beat anchors were not found in the narration."""
    if not timeline.get("unmatched"):
        return None
    ids = ", ".join(str(u.get("beat_id")) for u in timeline["unmatched"])
    return f"visual_timeline has unresolved narration anchors ({ids}); recompile before rendering."
