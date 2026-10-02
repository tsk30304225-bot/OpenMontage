"""Compare two behaviour recordings from tests.equivalence.recorder_plugin.

    python -m tests.equivalence.compare before.json after.json [--control control.json]

Every difference between ``before`` and ``after`` is a failure, with two
documented exceptions:

1. ``IGNORED_PATH_SUFFIXES`` — version stamps of external CLIs fetched on
   demand; compared nowhere.
2. ``NOISE_FIELDS`` — values that are random by test design. A difference is
   tolerated only when BOTH hold: the test's control recording (a second run of
   the *before* code) already differs from ``before``, and the differing path
   is one of the confirmed noise fields below. Any other difference in such a
   test (a verdict, a status, an issue count, a video frame hash) is real.

Tests whose outcome differs between recordings are listed. Exit 0 only when no
real difference remains.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_INDEX_RE = re.compile(r"\[\d+\]")

# Version stamps of external CLIs fetched on demand (npx hyperframes auto-updates
# between runs); they describe the environment, not this code.
IGNORED_PATH_SUFFIXES = ("._meta.version",)

# Confirmed noise (tests/tools/test_final_audio_delivery.py synthesizes unseeded
# anoisesrc pink noise; two runs of the same code differ exactly here):
#   - loudness readings of that audio
#   - the decoded AUDIO frame hash of files rendered from it (video hash stays strict)
#   - the final MP4 size, which follows the audio content
#   - issue messages that quote a reading: equal once numbers are masked
NOISE_LEAF_KEYS = {"integrated_lufs", "lra_lu", "true_peak_dbtp"}
NOISE_PATH_SUFFIXES = (".frames.audio", ".technical_probe.file_size_bytes")
_ISSUE_RE = re.compile(r"\.issues\[\d+\]$")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _diffs(a: Any, b: Any, path: str, out: list[str]) -> None:
    if type(a) is not type(b):
        out.append(path)
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}")
            else:
                _diffs(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}#len")
        for i, (x, y) in enumerate(zip(a, b)):
            _diffs(x, y, f"{path}[{i}]", out)
    elif a != b and not path.endswith(IGNORED_PATH_SUFFIXES):
        out.append(path)


def _get(rec: Any, path: str) -> Any:
    """Value at a diff path (keys may not contain dots; file-capture keys are never looked up)."""
    cur = rec
    for key, idx in re.findall(r"\.([^.\[#]+)|\[(\d+)\]", path):
        try:
            cur = cur[int(idx)] if idx else cur[key]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _value(rec: Any, path: str) -> str:
    return json.dumps(_get(rec, path), ensure_ascii=False)[:160]


def _is_noise(path: str, a_rec: Any, b_rec: Any) -> bool:
    if path.rsplit(".", 1)[-1] in NOISE_LEAF_KEYS or path.endswith(NOISE_PATH_SUFFIXES):
        return True
    if _ISSUE_RE.search(path):
        a, b = _get(a_rec, path), _get(b_rec, path)
        return isinstance(a, str) and isinstance(b, str) and _NUMBER_RE.sub("#", a) == _NUMBER_RE.sub("#", b)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--control", help="second recording of the before code")
    a = ap.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    before, after = load(a.before), load(a.after)
    control = load(a.control) if a.control else None

    missing = sorted(set(before["patched"]) - set(after["patched"]))
    rb, ra = before["records"], after["records"]
    rc = control["records"] if control else {}

    noisy: dict[str, set[str]] = {}
    if control:
        for t in set(rb) | set(rc):
            d: list[str] = []
            _diffs(rb.get(t), rc.get(t), "", d)
            if d:
                noisy[t] = {_INDEX_RE.sub("[]", p) for p in d}

    real: dict[str, list[str]] = {}
    nondeterministic: dict[str, list[str]] = {}
    for t in sorted(set(rb) | set(ra)):
        d: list[str] = []
        _diffs(rb.get(t), ra.get(t), "", d)
        for p in d:
            tolerated = t in noisy and _is_noise(p, rb.get(t), ra.get(t))
            (nondeterministic if tolerated else real).setdefault(t, []).append(p)

    outcome_changes = {t: (before.get("outcomes", {}).get(t), after.get("outcomes", {}).get(t))
                       for t in set(before.get("outcomes", {})) | set(after.get("outcomes", {}))
                       if not t.endswith(":: detail")
                       and before.get("outcomes", {}).get(t) != after.get("outcomes", {}).get(t)}

    for t, paths in list(real.items())[:15]:
        print(f"DIFF {t}")
        for p in paths[:3]:
            print(f"   {p}: {_value(rb.get(t), p)}  !=  {_value(ra.get(t), p)}")
    for t, paths in nondeterministic.items():
        print(f"NOISE (confirmed field, test varies in control) {t}: {len(paths)} value(s), e.g. {paths[0]}")
    for t, (x, y) in sorted(outcome_changes.items()):
        print(f"OUTCOME {t}: {x} -> {y}")
    if missing:
        print("targets recorded before but not found after:", missing)

    calls = sum(len(v) for v in rb.values())
    caps = [c for v in rb.values() for e in v for c in e.get("files", {}).values()]
    videos = sum(1 for c in caps if isinstance(c, dict) and "frames" in c)
    print(f"tests {len(set(rb) | set(ra))} | calls {calls} | file captures {len(caps)} (rendered videos {videos}) | "
          f"targets {len(before['patched'])} | real differences {len(real)} tests | "
          f"nondeterministic {len(nondeterministic)} tests | outcome changes {len(outcome_changes)}")
    return 1 if real or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
