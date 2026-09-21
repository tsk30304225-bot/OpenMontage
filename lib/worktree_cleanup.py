"""Remove a git worktree without deleting what its junctions point to.

On Windows, ``git worktree remove --force`` recurses through NTFS junctions
and deletes the *target's* contents (verified with git 2.53.0.windows.2).
OpenMontage worktrees junction shared data into every checkout
(``remotion-composer/node_modules`` -> the main checkout, ``tools/local`` and
two skills -> local-overlay), so a plain remove empties those for everyone.

``safe_remove_worktree`` unlinks every junction / symlink first (the link, not
the target), verifies none remain and every external target is intact, and
only then runs ``git worktree remove``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def find_links(root: Path) -> list[Path]:
    """Every junction/symlink under ``root``; never descends into one."""
    links: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        here = Path(dirpath)
        for name in list(dirnames):
            p = here / name
            if _is_link(p):
                links.append(p)
                dirnames.remove(name)
        links += [here / n for n in filenames if _is_link(here / n)]
    return links


def _target(link: Path) -> Path:
    try:
        return Path(os.readlink(link))
    except OSError:
        return link.resolve()


def _snapshot(target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"exists": False}
    if target.is_dir():
        return {"exists": True, "entries": sum(1 for _ in target.iterdir())}
    return {"exists": True, "bytes": target.stat().st_size}


def _unlink(link: Path) -> None:
    # A directory junction / dir symlink is removed with rmdir, which deletes
    # the reparse point only; a file symlink with unlink.
    if link.is_dir():
        os.rmdir(link)
    else:
        os.unlink(link)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _worktrees(any_checkout: Path) -> list[Path]:
    out = _git(["worktree", "list", "--porcelain"], any_checkout).stdout
    return [Path(line[len("worktree "):]).resolve() for line in out.splitlines() if line.startswith("worktree ")]


def safe_remove_worktree(path: str | os.PathLike, *, dry_run: bool = False) -> dict[str, Any]:
    wt = Path(path).resolve()
    report: dict[str, Any] = {"worktree": str(wt), "links": [], "removed": False, "problems": []}
    if not wt.is_dir():
        report["problems"].append(f"not a directory: {wt}")
        return report
    trees = _worktrees(wt)
    if not trees or wt not in trees:
        report["problems"].append(f"{wt} is not a registered git worktree")
        return report
    main = trees[0]
    if wt == main:
        report["problems"].append("refusing to remove the main checkout")
        return report

    for link in find_links(wt):
        target = _target(link)
        try:
            resolved = target.resolve()
            external = not resolved.is_relative_to(wt)
        except OSError:
            resolved, external = target, True
        report["links"].append({"link": str(link), "target": str(resolved), "external": external,
                                "before": _snapshot(resolved) if external else None})
    if dry_run:
        return report

    for row in report["links"]:
        _unlink(Path(row["link"]))
    leftover = find_links(wt)
    if leftover:
        report["problems"].append(f"links still present, not removing: {[str(p) for p in leftover]}")
        return report

    proc = _git(["worktree", "remove", "--force", str(wt)], main)
    if proc.returncode != 0:
        report["problems"].append(f"git worktree remove failed: {proc.stderr.strip()}")
        return report
    report["removed"] = not wt.exists()

    for row in report["links"]:
        if not row["external"]:
            continue
        row["after"] = _snapshot(Path(row["target"]))
        if row["after"] != row["before"]:
            report["problems"].append(f"external target changed: {row['target']} {row['before']} -> {row['after']}")
    return report
