"""Junction-safe worktree removal (Windows): the shared target must survive."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib.worktree_cleanup import find_links, safe_remove_worktree

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions are Windows-only")


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_junction(tmp_path):
    import _winapi

    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", str(wt), cwd=main)
    shared = tmp_path / "shared_node_modules"
    (shared / "pkg").mkdir(parents=True)
    (shared / "pkg" / "index.js").write_text("keep", encoding="utf-8")
    (wt / "remotion-composer").mkdir()
    _winapi.CreateJunction(str(shared), str(wt / "remotion-composer" / "node_modules"))
    (wt / "untracked.txt").write_text("local file", encoding="utf-8")
    return main, wt, shared


def test_dry_run_reports_external_links_and_changes_nothing(repo_with_junction) -> None:
    _, wt, shared = repo_with_junction
    report = safe_remove_worktree(wt, dry_run=True)
    assert report["problems"] == [] and not report["removed"]
    assert [(Path(r["link"]).name, r["external"]) for r in report["links"]] == [("node_modules", True)]
    assert (wt / "remotion-composer" / "node_modules").exists()


def test_junction_is_unlinked_target_survives_worktree_is_removed(repo_with_junction) -> None:
    main, wt, shared = repo_with_junction
    report = safe_remove_worktree(wt)
    assert report["problems"] == [], report["problems"]
    assert report["removed"] and not wt.exists()
    assert (shared / "pkg" / "index.js").read_text(encoding="utf-8") == "keep"
    listed = subprocess.run(["git", "worktree", "list"], cwd=main, capture_output=True, text=True).stdout
    assert "wt" not in listed.replace(str(main), "")


def test_refuses_main_checkout_and_non_worktrees(repo_with_junction, tmp_path) -> None:
    main, _, _ = repo_with_junction
    assert "main checkout" in safe_remove_worktree(main)["problems"][0]
    other = tmp_path / "plain"
    other.mkdir()
    assert safe_remove_worktree(other)["problems"]


def test_find_links_never_descends_into_a_junction(repo_with_junction) -> None:
    _, wt, _ = repo_with_junction
    links = find_links(wt)
    assert len(links) == 1 and os.path.isjunction(links[0])
