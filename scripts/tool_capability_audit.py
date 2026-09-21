"""Audit which tools this machine can actually route to.

Classifies every tool route offer on the evidence ladder
(DISCOVERED -> AVAILABLE -> SMOKE_TESTED -> OUTPUT_VERIFIED -> PRODUCTION_VERIFIED)
and marks the ones the tool router may pick (``routable``).

    python scripts/tool_capability_audit.py            # status + stored evidence only, no calls
    python scripts/tool_capability_audit.py --smoke    # + smallest real call per FREE offer
    python scripts/tool_capability_audit.py --smoke --only pexels_video hyperframes_compose

Paid or subscription offers are never called unless their tier is passed with
``--allow-cost-tier`` (get the user's approval first). The report and evidence
live in the machine-level audit dir (``~/.openmontage/tool_audit`` or
``$OPENMONTAGE_TOOL_AUDIT_DIR``), shared by every checkout and never committed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lib.tool_routing import audit_dir, audit_tools  # noqa: E402


def default_projects_roots() -> list[Path]:
    """This checkout's projects/ plus the main checkout's when run from a worktree."""
    roots = [REPO / "projects"]
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return roots
    if common:
        main = Path(common).parent / "projects"
        if main.resolve() != roots[0].resolve():
            roots.append(main)
    return roots


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="make the smallest real call per approved offer")
    ap.add_argument("--allow-cost-tier", action="append", default=[], choices=["subscription", "paid"],
                    help="also smoke offers of this cost tier (requires user approval)")
    ap.add_argument("--only", nargs="+", help="limit smoke calls to these tool names")
    ap.add_argument("--projects-root", action="append", type=Path,
                    help="project root scanned for production evidence (repeatable)")
    ap.add_argument("--output", type=Path, help="report path (default: <audit dir>/tool_capability.json)")
    args = ap.parse_args(argv)

    from tools.tool_registry import registry

    registry.discover()
    report = audit_tools(
        registry._tools.values(),
        run_smoke=args.smoke,
        allow_cost_tiers=["free", *args.allow_cost_tier],
        only=args.only,
        projects_roots=args.projects_root or default_projects_roots(),
    )
    out = args.output or audit_dir() / "tool_capability.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'offer':22} {'tool':22} {'level':20} {'routable':8}  blocked by")
    for o in report["offers"]:
        blocked = "; ".join(o["blocked_by"])[:90]
        print(f"{o['offer']:22} {o['tool']:22} {o['evidence_level']:20} {'yes' if o['routable'] else 'no':8}  {blocked}")
    s = report["summary"]
    print(f"\n{s['routable']}/{s['offers']} offers routable; axes without a routable offer: "
          f"{', '.join(s['axes_without_routable_offer']) or 'none'}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
