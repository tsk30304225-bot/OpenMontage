"""Narration phrase captions (``subtitles.style="karaoke"``) for stock Remotion compositions.

Wires word timings to the shared PhraseCaptions component
(``remotion-composer/src/components/PhraseCaptions.tsx``). Called by
``video_compose`` through ``lib/compose_hooks.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# subtitles.style values rendered by the shared PhraseCaptions component
# (remotion-composer/src/components/PhraseCaptions.tsx).
PHRASE_CAPTION_STYLES = frozenset({"karaoke"})


def caption_words_from_timing(timing: Any) -> list[dict[str, Any]]:
    """Convert word timings (global seconds) into Remotion WordCaption dicts.

    Accepts qwen3_tts output: ``data["timestamps"]`` (list of segments), the
    ``timestamps_path`` file (``{"segments": [...]}``) or the flat
    ``word_timestamps_path`` file (``{"word_timestamps": [...]}``). The last
    word of each segment gets ``pageBreakAfter`` so a phrase never spans two
    narration segments.
    """
    if isinstance(timing, dict):
        if "segments" in timing:
            groups = [seg.get("words") or [] for seg in timing["segments"]]
        else:
            groups = [timing.get("word_timestamps") or []]
    elif isinstance(timing, list):
        if timing and isinstance(timing[0], dict) and "words" in timing[0]:
            groups = [seg.get("words") or [] for seg in timing]
        else:
            groups = [timing]
    else:
        return []

    captions: list[dict[str, Any]] = []
    for group in groups:
        words = [w for w in group if str(w.get("word", "")).strip()]
        for index, w in enumerate(words):
            caption: dict[str, Any] = {
                "word": str(w["word"]).strip(),
                "startMs": int(round(float(w["start"]) * 1000)),
                "endMs": int(round(float(w["end"]) * 1000)),
            }
            if index == len(words) - 1:
                caption["pageBreakAfter"] = True
            captions.append(caption)
    return captions


def attach_phrase_captions(props: dict[str, Any], composition_id: str) -> str | None:
    """Wire ``subtitles.style="karaoke"`` to PhraseCaptions for stock compositions.

    Loads word timings from ``subtitles.source`` when the props carry no
    captions yet. Returns an error message when the style is selected but no
    word timings are available — rendering silently without captions would
    break the approved subtitle promise.
    """
    subs = props.get("subtitles")
    if not isinstance(subs, dict):
        return None
    style = str(subs.get("style") or "").strip().lower()
    if style not in PHRASE_CAPTION_STYLES or subs.get("enabled") is False:
        return None

    existing = props.get("captions")
    words = existing.get("words") if isinstance(existing, dict) else existing
    if not words:
        source = subs.get("source")
        path = Path(str(source)) if source else None
        if path is None or path.suffix.lower() != ".json" or not path.is_file():
            return (
                f"subtitles.style={style!r} renders phrase captions from real word "
                "timings, but none were provided. Pass props 'captions' "
                "([{word, startMs, endMs}]) or set subtitles.source to a qwen3_tts "
                f"timestamps JSON (timestamps_path or word_timestamps_path). Got source={source!r}."
            )
        try:
            words = caption_words_from_timing(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return f"Could not read caption word timings from {path}: {exc}"
        if not words:
            return f"No word timings found in {path}."

    if composition_id == "CinematicRenderer":
        config = dict(existing) if isinstance(existing, dict) else {}
        config["words"] = words
        config.setdefault("style", style)
        for src_key, dst_key in (
            ("font", "fontFamily"),
            ("font_size", "fontSize"),
            ("color", "color"),
            ("dim_color", "dimColor"),
            ("background", "backgroundColor"),
            ("position", "position"),
            ("max_chars_per_cue", "maxCharsPerCue"),
            ("hold_seconds", "holdSeconds"),
        ):
            if subs.get(src_key) is not None:
                config.setdefault(dst_key, subs[src_key])
        props["captions"] = config
    else:
        props["captions"] = words
    return None
