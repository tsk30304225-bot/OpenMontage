"""Behaviour recorder for refactor equivalence checks.

Load as a pytest plugin while running the existing tests:

    OM_RECORD_OUT=before.json python -m pytest -p tests.equivalence.recorder_plugin <tests>

Every call to a function listed in TARGETS is recorded per test: arguments
before and after the call (callers mutate props in place), the return value or
raised exception, the content of JSON/JS files the result points at, and a frame
hash of rendered video files. Each logical target names its old and new
locations; whichever exists in the current checkout is patched, so the same
plugin records both sides of a move. Compare two recordings with
``python -m tests.equivalence.compare before.json after.json``.

Volatile values (wall-clock durations, pytest/tempfile directories) are
normalized so two runs of unchanged code compare equal.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# logical name -> candidate locations "module:attr" or "module:Class.attr" (first that exists wins)
TARGETS: dict[str, list[str]] = {
    # contract semantics (pure)
    "contract.validate_direction": ["lib.direction_contract.contract:validate_direction", "lib.visual_direction:validate_direction"],
    "contract.compile_timeline": ["lib.direction_contract.contract:compile_timeline", "lib.visual_direction:compile_timeline"],
    "contract.ineffective_events": ["lib.direction_contract.contract:ineffective_events", "lib.visual_direction:ineffective_events"],
    "contract.state_at": ["lib.direction_contract.contract:state_at", "lib.visual_direction:state_at"],
    # implementation binding / trace
    "binding.scan_project": ["lib.direction_contract.binding.remotion_source:scan_project", "lib.atelier_direction:scan_project"],
    "binding.build_trace": ["lib.direction_contract.binding.remotion_source:build_trace", "lib.atelier_direction:build_trace"],
    "binding.scene_events": ["lib.direction_contract.binding.hyperframes:scene_events", "lib.scene_runtime:scene_events"],
    "binding.write_bridge": ["lib.direction_contract.binding.hyperframes:write_bridge", "lib.scene_runtime:write_bridge"],
    "binding.trace_workspace": ["lib.direction_contract.binding.hyperframes:trace_workspace", "lib.scene_runtime:trace_workspace"],
    "binding.hyperframes_cuts": ["lib.direction_contract.binding.hyperframes:hyperframes_cuts", "lib.scene_runtime:hyperframes_cuts"],
    "binding.without_scene_events": ["lib.direction_contract.binding.hyperframes:without_scene_events", "lib.scene_runtime:without_scene_events"],
    # scene runtimes
    "runtime.approved_runtimes": ["lib.scene_runtime:approved_runtimes"],
    "runtime.resolve_scene_runtimes": ["lib.scene_runtime:resolve_scene_runtimes"],
    "runtime.planned_runtime_gaps": ["lib.scene_runtime:planned_runtime_gaps"],
    "runtime.render_scene_runtimes": ["lib.scene_runtime:render_scene_runtimes", "tools.video.video_compose:VideoCompose._render_scene_runtimes"],
    "runtime.is_media_source": ["lib.scene_runtime:is_media_source", "tools.video.video_compose:VideoCompose._is_media_source"],
    # render guards
    "guards.attach_visual_timeline": ["lib.direction_contract.guards:attach_visual_timeline", "tools.video.video_compose:VideoCompose._attach_visual_timeline"],
    "guards.prepare_atelier_direction": ["lib.direction_contract.guards:prepare_atelier_direction", "tools.video.video_compose:VideoCompose._prepare_atelier_direction"],
    # captions
    "captions.caption_words_from_timing": ["lib.phrase_captions:caption_words_from_timing", "tools.video.video_compose:VideoCompose._caption_words_from_timing"],
    "captions.attach_phrase_captions": ["lib.phrase_captions:attach_phrase_captions", "tools.video.video_compose:VideoCompose._attach_phrase_captions"],
    # atelier policy
    "atelier.classify_import": ["lib.atelier_policy:classify_import", "tools.video.video_compose:VideoCompose._classify_atelier_import"],
    "atelier.run_checks": ["tools.video.video_compose:VideoCompose._run_atelier_checks"],
    # audio delivery
    "audio.resolve_contract": ["lib.audio_delivery:resolve_contract"],
    "audio.deliver": ["lib.audio_delivery:deliver"],
    "audio.measure": ["lib.audio_delivery:measure"],
    "audio.evaluate": ["lib.audio_delivery:evaluate"],
    # checkpoint
    "checkpoint.validate_direction_stage": ["lib.direction_contract.hooks:validate_scene_plan_direction", "lib.checkpoint:_validate_direction_contract"],
    "checkpoint.validate_checkpoint": ["lib.checkpoint:validate_checkpoint"],
    # tool entry points (end-to-end behaviour)
    "tool.video_compose": ["tools.video.video_compose:VideoCompose.execute"],
    "tool.direction_qa": ["tools.analysis.direction_qa:DirectionQA.execute"],
    "tool.visual_timeline_compiler": ["tools.video.visual_timeline_compiler:VisualTimelineCompiler.execute"],
    "tool.hyperframes_compose": ["tools.video.hyperframes_compose:HyperFramesCompose.execute"],
}

VOLATILE_KEYS = {"duration_seconds", "duration_s", "elapsed_seconds", "wall_time", "render_seconds",
                 "started_at", "finished_at", "created_at", "timestamp", "generated_at"}

_TMP_PATTERNS = [
    (re.compile(r"pytest-of-[^\\/]+[\\/]+pytest-\d+"), "<PYTEST>"),
    (re.compile(r"(?<=[\\/])tmp[a-z0-9_]{6,}"), "<TMPDIR>"),
    (re.compile(r"(?<=[\\/])om_[a-z_]+_[a-z0-9_]{6,}"), "<OMTMP>"),
]

RECORDS: dict[str, list[dict[str, Any]]] = {}
PATCHED: dict[str, str] = {}
_STATE = {"test": "<session>", "depth": 0}
_FILE_CACHE: dict[tuple[str, int, int], Any] = {}


def _norm(s: str) -> str:
    for pat, rep in _TMP_PATTERNS:
        s = pat.sub(rep, s)
    return s.replace("\\\\", "/").replace("\\", "/")


def _canon(x: Any, depth: int = 0) -> Any:
    if depth > 40:
        return "<deep>"
    if x is None or isinstance(x, (bool, int)):
        return x
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, (str, Path)):
        return _norm(str(x))
    if isinstance(x, dict):
        return {str(k): _canon(v, depth + 1) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))
                if str(k) not in VOLATILE_KEYS}
    if isinstance(x, (set, frozenset)):
        return sorted((_canon(v, depth + 1) for v in x), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(x, (list, tuple)):
        return [_canon(v, depth + 1) for v in x]
    if isinstance(x, BaseException):
        return {"__raises__": type(x).__name__, "message": _norm(str(x))}
    if hasattr(x, "success") and hasattr(x, "error") and hasattr(x, "data"):  # ToolResult
        if not x.success:  # same shape a lib helper returns for an error
            return {"error": _canon(x.error, depth + 1), "data": _canon(x.data, depth + 1)}
        return {"__tool_result__": True, "error": _canon(x.error, depth + 1), "data": _canon(x.data, depth + 1),
                "artifacts": _canon(x.artifacts, depth + 1)}
    if isinstance(x, type):
        return f"<class {x.__name__}>"
    return f"<{type(x).__name__}>"


def _frame_hash(path: Path) -> dict[str, str]:
    """Decoded-frame hash per stream type, so a random test audio source cannot mask the picture."""
    out: dict[str, str] = {}
    for kind, sel in (("video", "0:v"), ("audio", "0:a")):
        cp = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", sel, "-f", "framemd5", "-"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        lines = [ln for ln in cp.stdout.splitlines() if ln and not ln.startswith("#")]
        if lines:
            out[kind] = f"framemd5:{len(lines)}:{hashlib.sha256(chr(10).join(lines).encode()).hexdigest()[:16]}"
    return out


def _file_content(path_str: str) -> Any:
    p = Path(path_str)
    try:
        if not p.is_file():
            return None
        st = p.stat()
    except (OSError, ValueError):
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key in _FILE_CACHE:
        return _FILE_CACHE[key]
    suffix = p.suffix.lower()
    out: Any = None
    try:
        if suffix == ".json" and st.st_size < 5_000_000:
            out = {"json": _canon(json.loads(p.read_text(encoding="utf-8")))}
        elif suffix == ".js" and st.st_size < 2_000_000:
            out = {"js_sha": hashlib.sha256(_norm(p.read_text(encoding="utf-8")).encode()).hexdigest()[:16]}
        elif suffix in (".mp4", ".mov", ".webm"):
            out = {"frames": _frame_hash(p)}
    except Exception as exc:  # noqa: BLE001 - recording must never break a test
        out = {"unreadable": type(exc).__name__}
    _FILE_CACHE[key] = out
    return out


def _files_in(value: Any, found: dict[str, Any], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        if len(value) < 400 and value.lower().endswith((".json", ".js", ".mp4", ".mov", ".webm")):
            content = _file_content(value)
            if content is not None:
                found[_norm(value)] = content
    elif isinstance(value, dict):
        for v in value.values():
            _files_in(v, found, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _files_in(v, found, depth + 1)
    elif hasattr(value, "success") and hasattr(value, "data"):
        _files_in(value.data, found, depth + 1)
        _files_in(getattr(value, "artifacts", []), found, depth + 1)


def _wrap(key: str, fn: Any) -> Any:
    sig = None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        pass

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            bound = sig.bind_partial(*args, **kwargs) if sig else None
            # injected callables (e.g. a renderer passed into a lib helper) are wiring, not behaviour
            named = ({k: v for k, v in bound.arguments.items()
                      if k not in ("self", "cls") and not (callable(v) and not isinstance(v, type))}
                     if bound else {"args": args, "kwargs": kwargs})
        except TypeError:
            named = {"args": args, "kwargs": kwargs}
        before = _canon(named)
        entry: dict[str, Any] = {"fn": key, "depth": _STATE["depth"], "args": before}
        RECORDS.setdefault(_STATE["test"], []).append(entry)
        _STATE["depth"] += 1
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            entry["raises"] = _canon(exc)
            raise
        finally:
            _STATE["depth"] -= 1
        after = _canon(named)
        if after != before:
            entry["args_after"] = after
        entry["result"] = _canon(result)
        files: dict[str, Any] = {}
        _files_in(result, files)
        if files:
            entry["files"] = files
        return result

    wrapper.__om_recorded__ = key  # type: ignore[attr-defined]
    return wrapper


def _patch(key: str, spec: str) -> bool:
    mod_name, _, attr = spec.partition(":")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return False
    if "." in attr:
        cls_name, name = attr.split(".", 1)
        cls = getattr(mod, cls_name, None)
        raw = cls.__dict__.get(name) if cls is not None else None
        if raw is None:
            return False
        if isinstance(raw, staticmethod):
            setattr(cls, name, staticmethod(_wrap(key, raw.__func__)))
        elif isinstance(raw, classmethod):
            setattr(cls, name, classmethod(_wrap(key, raw.__func__)))
        else:
            setattr(cls, name, _wrap(key, raw))
        return True
    orig = getattr(mod, attr, None)
    if orig is None or not callable(orig):
        return False
    wrapper = _wrap(key, orig)
    for m in list(sys.modules.values()):  # rebind every module that imported the function by name
        d = getattr(m, "__dict__", None)
        if not d:
            continue
        for name, value in list(d.items()):
            if value is orig:
                d[name] = wrapper
    return True


def pytest_collection_finish(session: pytest.Session) -> None:
    for key, candidates in TARGETS.items():
        for spec in candidates:
            if _patch(key, spec):
                PATCHED[key] = spec
                break


OUTCOMES: dict[str, str] = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: Any):  # noqa: ARG001
    _STATE["test"] = item.nodeid
    yield
    _STATE["test"] = "<session>"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or report.outcome != "passed":
        if OUTCOMES.get(report.nodeid) in (None, "passed"):
            OUTCOMES[report.nodeid] = report.outcome
            if report.outcome == "failed":
                OUTCOMES[report.nodeid + " :: detail"] = _norm(str(report.longrepr))[-1500:]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    out = os.environ.get("OM_RECORD_OUT")
    if not out:
        return
    Path(out).write_text(json.dumps({"patched": PATCHED, "outcomes": OUTCOMES, "records": RECORDS},
                                    ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
