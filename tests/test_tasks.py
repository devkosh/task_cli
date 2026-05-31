"""
test_tasks.py — Skeleton test suite for tasks.py edge cases (SEC-13).

Each test function corresponds to one edge case from the SEC-13 issue.
No assertions are implemented — these are stubs for the Developer agent.
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 1: No AI CLI available
# ---------------------------------------------------------------------------

def test_no_ai_cli_available():
    """find_ai_cli() returns None when none of claude/codex/agy are on PATH.

    Setup: monkeypatch shutil.which to always return None.
    Assert: find_ai_cli() returns None and cmd_work raises a user-visible error
            rather than an unhandled exception.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 2: fzf absent → numbered list fallback
# ---------------------------------------------------------------------------

def test_fzf_absent_falls_back_to_numbered_list(tmp_path, monkeypatch):
    """pick_task() uses _numbered_list_pick() when fzf is not on PATH.

    Setup: monkeypatch shutil.which so 'fzf' returns None; provide a list of
           two fake task paths; simulate stdin input of '1'.
    Assert: pick_task() returns the first task without raising.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 3: Corrupt / missing frontmatter
# ---------------------------------------------------------------------------

def test_corrupt_frontmatter_does_not_crash(tmp_path):
    """read_frontmatter() returns an empty dict when CLAUDE.md has invalid YAML.

    Setup: write a CLAUDE.md with broken YAML (e.g., unclosed block scalar).
    Assert: read_frontmatter() returns {} (or a safe default), does not raise.
    """
    ...


def test_missing_claude_md_returns_empty_dict(tmp_path):
    """read_frontmatter() returns an empty dict when the file does not exist.

    Setup: pass a path to a non-existent CLAUDE.md.
    Assert: read_frontmatter() returns {} without raising FileNotFoundError.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 4: Iteration rollback
# ---------------------------------------------------------------------------

def test_next_iteration_after_rollback(tmp_path):
    """next_iteration() correctly handles gaps in iteration numbering.

    Setup: create iterations/1_work_..., iterations/3_work_... (gap at 2).
    Assert: next_iteration() returns 4 (max + 1), not 2 (first gap).
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 5: tasks done with no declared deliverables
# ---------------------------------------------------------------------------

def test_done_with_no_deliverables_does_not_crash(tmp_path):
    """cmd_done() completes gracefully when task.md has an empty Deliverables section.

    Setup: write a minimal task.md with '## Deliverables' but no list items;
           write a matching CLAUDE.md with deliverables: [].
    Assert: detect_outputs() returns [] and confirm_outputs() does not crash.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 6: tasks done when declared file doesn't exist (warn, not crash)
# ---------------------------------------------------------------------------

def test_done_warns_on_missing_declared_file(tmp_path, capsys):
    """detect_outputs() warns but does not crash when a declared deliverable is absent.

    Setup: task.md declares 'slides_v1.md'; the file does NOT exist in task_dir.
    Assert: detect_outputs() returns [] for existing files; confirm_outputs() prints
            a warning mentioning the missing filename; no exception is raised.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 7: Multi-task session
# ---------------------------------------------------------------------------

def test_list_tasks_returns_all_tasks_in_session(tmp_path, monkeypatch):
    """list_tasks(filter_session=...) returns all tasks for that session folder.

    Setup: create TASKS_ROOT/31052026/task-a/CLAUDE.md and task-b/CLAUDE.md;
           also create TASKS_ROOT/01062026/task-c/CLAUDE.md (different session).
    Assert: list_tasks(filter_session='31052026') returns exactly 2 paths.
    """
    ...


# ---------------------------------------------------------------------------
# SEC-13 Edge Case 8: ruamel.yaml write-back preserves body text and comments
# ---------------------------------------------------------------------------

def test_write_frontmatter_preserves_body_and_comments(tmp_path):
    """write_frontmatter() round-trips YAML without destroying Markdown body or inline comments.

    Setup: write a CLAUDE.md with YAML frontmatter containing an inline comment
           (e.g., '# keep this') and a Markdown body with headings and list items.
    Assert: after write_frontmatter() updates the 'status' key, the body text is
            unchanged and the inline comment is preserved.
    """
    ...
