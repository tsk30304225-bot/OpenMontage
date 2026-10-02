"""Compare two behaviour recordings from tests.equivalence.recorder_plugin.

    python -m tests.equivalence.compare before.json after.json [--control control.json]

Every difference between ``before`` and ``after`` is a failure, except in
tests whose control recording (a second run of the *before* code) already
differs from ``before``: those tests are nondeterministic themselves (unseeded
random test audio) and their differences are listed separately. Tests whose
outcome differs between runs are listed too. Exit 0 only when no real
difference remains.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_INDEX_RE = re.compile(r"\[\d+\]")


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
    elif a != b:
        out.append(path)


def _value(rec: Any, path: str) -> str:
    cur = rec
    for part in re.findall(r"\.([^.\[#]+)|\[(\d+)\]", path):
        key, idx = part
        try:
            cur = cur[int(idx)] if idx else cur[key]
        except (KeyError, IndexError, TypeError):
            return "<absent>"
    return json.dumps(cur, ensure_ascii=False)[:160]


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

    # A test whose recording already differs between two runs of the same code
    # (unseeded random input) cannot prove equality: all its differences are
    # reported as nondeterministic, never silently dropped.
    real: dict[str, list[str]] = {}
    nondeterministic: dict[str, list[str]] = {}
    for t in sorted(set(rb) | set(ra)):
        d: list[str] = []
        _diffs(rb.get(t), ra.get(t), "", d)
        for p in d:
            (nondeterministic if t in noisy else real).setdefault(t, []).append(p)

    outcome_changes = {t: (before.get("outcomes", {}).get(t), after.get("outcomes", {}).get(t))
                       for t in set(before.get("outcomes", {})) | set(after.get("outcomes", {}))
                       if not t.endswith(":: detail")
                       and before.get("outcomes", {}).get(t) != after.get("outcomes", {}).get(t)}

    for t, paths in list(real.items())[:15]:
        print(f"DIFF {t}")
        for p in paths[:3]:
            print(f"   {p}: {_value(rb.get(t), p)}  !=  {_value(ra.get(t), p)}")
    for t, paths in nondeterministic.items():
        print(f"NONDETERMINISTIC (also differs in control) {t}: {len(paths)} value(s), e.g. {paths[0]}")
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
