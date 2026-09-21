"""Remove an OpenMontage git worktree without deleting shared junction targets.

    python scripts/safe_worktree_remove.py D:\\path\\to\\worktree [--dry-run]

Never use ``git worktree remove --force`` directly on Windows for a worktree
that has junctions (node_modules, tools/local, local-overlay skills): git
follows them and empties the shared targets. See lib/worktree_cleanup.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.worktree_cleanup import safe_remove_worktree  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worktree")
    ap.add_argument("--dry-run", action="store_true", help="list links and targets, change nothing")
    args = ap.parse_args(argv)
    report = safe_remove_worktree(args.worktree, dry_run=args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
