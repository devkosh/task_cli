"""
test_tasks.py — Edge-case test suite for tasks.py (SEC-13).

Uses stdlib unittest only (no pytest dependency required).
"""

from __future__ import annotations

import sys
import os
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts/ to path so we can import tasks directly
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import tasks  # noqa: E402  (after sys.path manipulation)
from tasks import (
    find_ai_cli,
    run_ai_gen,
    _fzf_available,
    pick_task,
    _numbered_list_pick,
    read_frontmatter,
    write_frontmatter,
    next_iteration,
    detect_outputs,
    list_tasks,
)


# ---------------------------------------------------------------------------
# Edge Case 1: No AI CLI available
# ---------------------------------------------------------------------------

class TestNoAICLI(unittest.TestCase):
    """find_ai_cli() returns None; run_ai_gen() raises RuntimeError when no AI CLIs exist."""

    def test_find_ai_cli_returns_none(self):
        """shutil.which always returns None → find_ai_cli() returns None."""
        with patch("shutil.which", return_value=None):
            result = find_ai_cli()
        self.assertIsNone(result)

    def test_run_ai_gen_raises_runtime_error(self):
        """run_ai_gen raises RuntimeError when no AI CLI is found."""
        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                run_ai_gen("some prompt", Path("."))
        self.assertIn("No AI CLI", str(ctx.exception))


# ---------------------------------------------------------------------------
# Edge Case 2: fzf absent → numbered list fallback
# ---------------------------------------------------------------------------

class TestFzfFallback(unittest.TestCase):
    """pick_task falls back to _numbered_list_pick when fzf is not on PATH."""

    def test_fzf_available_returns_false_when_absent(self):
        """_fzf_available() returns False when fzf is not in PATH."""
        with patch("shutil.which", return_value=None):
            self.assertFalse(_fzf_available())

    def test_pick_task_falls_back_to_numbered_list(self):
        """pick_task calls _numbered_list_pick when fzf is absent and multiple tasks exist."""
        task_a = Path("31052026/task-a")
        task_b = Path("31052026/task-b")
        tasks_list = [task_a, task_b]

        # Patch _fzf_available to False and _numbered_list_pick to return index 0
        with patch("tasks._fzf_available", return_value=False), \
             patch("tasks._numbered_list_pick", return_value=0) as mock_pick:
            result = pick_task(tasks_list)

        mock_pick.assert_called_once()
        self.assertEqual(result, task_a)

    def test_numbered_list_pick_with_mocked_stdin(self):
        """_numbered_list_pick returns index 0 when user enters '1'."""
        items = ["31052026/task-a", "31052026/task-b"]
        with patch("builtins.input", return_value="1"):
            result = _numbered_list_pick(items)
        self.assertEqual(result, 0)  # 0-based index

    def test_numbered_list_pick_cancel(self):
        """_numbered_list_pick returns None when user enters 'q'."""
        items = ["31052026/task-a", "31052026/task-b"]
        with patch("builtins.input", return_value="q"):
            result = _numbered_list_pick(items)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Edge Case 3: Corrupt or missing frontmatter in CLAUDE.md
# ---------------------------------------------------------------------------

class TestFrontmatterEdgeCases(unittest.TestCase):
    """read_frontmatter handles missing files, missing delimiters, and valid YAML."""

    def test_read_frontmatter_missing_file(self):
        """read_frontmatter on a non-existent file returns {}."""
        result = read_frontmatter(Path("/nonexistent/path/CLAUDE.md"))
        self.assertEqual(result, {})

    def test_read_frontmatter_no_delimiters(self):
        """read_frontmatter on a file with no --- delimiters returns {}."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Just a heading\n\nSome body text with no frontmatter at all.\n")
            tmp_path = Path(f.name)
        try:
            result = read_frontmatter(tmp_path)
            self.assertEqual(result, {})
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_read_frontmatter_valid_yaml(self):
        """read_frontmatter on a file with valid YAML frontmatter returns the correct dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(
                "---\n"
                "slug: test-task\n"
                "type: planning\n"
                "status: todo\n"
                "---\n"
                "\n"
                "# test-task\n"
            )
            tmp_path = Path(f.name)
        try:
            result = read_frontmatter(tmp_path)
            self.assertEqual(result.get("slug"), "test-task")
            self.assertEqual(result.get("type"), "planning")
            self.assertEqual(result.get("status"), "todo")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_read_frontmatter_only_opening_delimiter(self):
        """read_frontmatter with only an opening --- but no closing --- returns {}."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nslug: incomplete\n# no closing delimiter\n")
            tmp_path = Path(f.name)
        try:
            result = read_frontmatter(tmp_path)
            self.assertEqual(result, {})
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Edge Case 4: Iteration rollback (tasks work again after tasks done)
# ---------------------------------------------------------------------------

class TestIterationTracking(unittest.TestCase):
    """next_iteration correctly computes max + 1 across mixed work/review files."""

    def test_next_iteration_after_work_and_review_cycles(self):
        """next_iteration with 1_work, 1_review, 2_work files returns 3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            iterations_dir = task_dir / "iterations"
            iterations_dir.mkdir()
            # Create the pattern described: 1_work, 1_review, 2_work
            (iterations_dir / "1_work_20260531_100000.md").write_text("w1")
            (iterations_dir / "1_review_20260531_110000.md").write_text("r1")
            (iterations_dir / "2_work_20260531_120000.md").write_text("w2")

            result = next_iteration(task_dir)
        self.assertEqual(result, 3)

    def test_next_iteration_empty_dir(self):
        """next_iteration on an empty iterations/ dir returns 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            (task_dir / "iterations").mkdir()
            result = next_iteration(task_dir)
        self.assertEqual(result, 1)

    def test_next_iteration_no_iterations_dir(self):
        """next_iteration when iterations/ doesn't exist returns 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = next_iteration(Path(tmpdir))
        self.assertEqual(result, 1)

    def test_next_iteration_with_gap(self):
        """next_iteration uses max+1, not first gap: files 1 and 3 → returns 4."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir)
            iterations_dir = task_dir / "iterations"
            iterations_dir.mkdir()
            (iterations_dir / "1_work_20260531_100000.md").write_text("w1")
            (iterations_dir / "3_work_20260531_120000.md").write_text("w3")

            result = next_iteration(task_dir)
        self.assertEqual(result, 4)


# ---------------------------------------------------------------------------
# Edge Case 5: tasks done with no declared deliverables
# ---------------------------------------------------------------------------

class TestDetectOutputs(unittest.TestCase):
    """detect_outputs handles missing task.md and empty Deliverables sections."""

    def test_detect_outputs_no_task_md(self):
        """detect_outputs on a task dir with no task.md returns []."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = detect_outputs(Path(tmpdir), n=1)
        self.assertEqual(result, [])

    def test_detect_outputs_empty_deliverables_section(self):
        """detect_outputs on task.md with empty ## Deliverables returns []."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "# Task\n\n"
                "## Goal\nDo stuff.\n\n"
                "## Deliverables\n\n"
                "## Notes\nNone.\n",
                encoding="utf-8",
            )
            result = detect_outputs(Path(tmpdir), n=1)
        self.assertEqual(result, [])

    def test_detect_outputs_with_deliverables(self):
        """detect_outputs correctly parses deliverable names from task.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "# Task\n\n"
                "## Deliverables\n"
                "- report_v1.md\n"
                "- slides_v1.pdf\n"
                "\n"
                "## Notes\n",
                encoding="utf-8",
            )
            result = detect_outputs(Path(tmpdir), n=1)
        self.assertEqual(result, ["report_v1.md", "slides_v1.pdf"])

    def test_detect_outputs_with_em_dash_description(self):
        """detect_outputs strips the em-dash description, returning only the filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "## Deliverables\n"
                "- report_v1.md — Main report document\n",
                encoding="utf-8",
            )
            result = detect_outputs(Path(tmpdir), n=1)
        self.assertEqual(result, ["report_v1.md"])

    def test_detect_outputs_versions_deliverable(self):
        """detect_outputs applies iteration versioning to deliverable names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "## Deliverables\n"
                "- report_v1.md\n",
                encoding="utf-8",
            )
            # n=3 should update _v1 → _v3
            result = detect_outputs(Path(tmpdir), n=3)
        self.assertEqual(result, ["report_v3.md"])


# ---------------------------------------------------------------------------
# Edge Case 6: tasks done when declared file doesn't exist (warn, not crash)
# ---------------------------------------------------------------------------

class TestMissingDeliverable(unittest.TestCase):
    """detect_outputs lists declared deliverables without crashing if they don't exist on disk."""

    def test_detect_outputs_does_not_check_disk(self):
        """detect_outputs returns the declared filename even if the file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "## Deliverables\n"
                "- slides_v1.md\n",
                encoding="utf-8",
            )
            # The file slides_v1.md does NOT exist in tmpdir
            self.assertFalse((Path(tmpdir) / "slides_v1.md").exists())

            # detect_outputs should return it without crashing
            result = detect_outputs(Path(tmpdir), n=1)

        self.assertEqual(result, ["slides_v1.md"])

    def test_detect_outputs_returns_list_of_names_not_paths(self):
        """detect_outputs returns plain string filenames, not Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_md = Path(tmpdir) / "task.md"
            task_md.write_text(
                "## Deliverables\n"
                "- output_v1.md\n",
                encoding="utf-8",
            )
            result = detect_outputs(Path(tmpdir), n=1)

        self.assertTrue(all(isinstance(r, str) for r in result))


# ---------------------------------------------------------------------------
# Edge Case 7: Multi-task session (same DDMMYYYY, two slugs)
# ---------------------------------------------------------------------------

class TestMultiTaskSession(unittest.TestCase):
    """list_tasks with a fake task root containing multiple sessions and slugs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmp_root = Path(self.tmpdir)

        # Session 31052026: two tasks
        for slug in ("task-a", "task-b"):
            d = self.tmp_root / "31052026" / slug
            d.mkdir(parents=True)
            (d / "CLAUDE.md").write_text(
                f"---\nslug: {slug}\ntype: planning\nstatus: todo\n---\n",
                encoding="utf-8",
            )

        # Session 01012026: one task (different session)
        d = self.tmp_root / "01012026" / "task-c"
        d.mkdir(parents=True)
        (d / "CLAUDE.md").write_text(
            "---\nslug: task-c\ntype: reporting\nstatus: done\n---\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_tasks_returns_all_tasks_in_session(self):
        """list_tasks(filter_session='31052026') returns exactly 2 tasks."""
        with patch.object(tasks, "TASKS_ROOT", self.tmp_root):
            result = list_tasks(filter_session="31052026")
        self.assertEqual(len(result), 2)
        slugs = {p.parts[1] for p in result}
        self.assertIn("task-a", slugs)
        self.assertIn("task-b", slugs)

    def test_list_tasks_session_filter_excludes_other(self):
        """list_tasks(filter_session='01012026') returns only task-c."""
        with patch.object(tasks, "TASKS_ROOT", self.tmp_root):
            result = list_tasks(filter_session="01012026")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].parts[1], "task-c")

    def test_list_tasks_wrong_session_returns_empty(self):
        """list_tasks(filter_session='01062026') returns [] (no such session)."""
        with patch.object(tasks, "TASKS_ROOT", self.tmp_root):
            result = list_tasks(filter_session="01062026")
        self.assertEqual(result, [])

    def test_list_tasks_no_filter_returns_all(self):
        """list_tasks() with no filter returns all 3 tasks across both sessions."""
        with patch.object(tasks, "TASKS_ROOT", self.tmp_root):
            result = list_tasks()
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# Edge Case 8: ruamel.yaml write-back preserves body text
# ---------------------------------------------------------------------------

class TestYamlRoundtrip(unittest.TestCase):
    """write_frontmatter preserves markdown body text and all frontmatter fields."""

    def test_roundtrip_preserves_all_frontmatter_fields(self):
        """All written frontmatter keys are readable back correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = Path(tmpdir) / "CLAUDE.md"
            data = {
                "slug": "roundtrip-test",
                "type": "planning",
                "status": "todo",
                "session": "31052026",
                "deliverables": ["output_v1.md"],
                "outputs": [],
            }
            write_frontmatter(claude_md, data)
            result = read_frontmatter(claude_md)

        self.assertEqual(result.get("slug"), "roundtrip-test")
        self.assertEqual(result.get("type"), "planning")
        self.assertEqual(result.get("status"), "todo")
        self.assertEqual(result.get("session"), "31052026")
        self.assertEqual(result.get("deliverables"), ["output_v1.md"])

    def test_write_frontmatter_preserves_body_text(self):
        """Body text after --- is preserved when frontmatter is updated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = Path(tmpdir) / "CLAUDE.md"
            body_text = "\n# My Task\n\nThis body should survive the round-trip.\n\n## Goal\nDo things.\n"

            # Write initial CLAUDE.md with frontmatter + body
            claude_md.write_text(
                "---\nslug: body-test\nstatus: todo\n---\n" + body_text,
                encoding="utf-8",
            )

            # Update frontmatter (status change)
            data = {"slug": "body-test", "status": "in_progress"}
            write_frontmatter(claude_md, data)

            # Read back full file content
            full_content = claude_md.read_text(encoding="utf-8")

        # Body should be preserved verbatim
        self.assertIn("This body should survive the round-trip.", full_content)
        self.assertIn("## Goal", full_content)
        self.assertIn("Do things.", full_content)

    def test_write_then_read_frontmatter_status_updated(self):
        """After write_frontmatter updates status, read_frontmatter returns the new status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = Path(tmpdir) / "CLAUDE.md"
            # Initial write
            claude_md.write_text(
                "---\nslug: status-test\nstatus: todo\n---\n\n# status-test\n",
                encoding="utf-8",
            )
            # Update
            data = {"slug": "status-test", "status": "done"}
            write_frontmatter(claude_md, data)
            # Read back
            result = read_frontmatter(claude_md)

        self.assertEqual(result.get("status"), "done")
        self.assertEqual(result.get("slug"), "status-test")

    def test_write_frontmatter_creates_file_if_absent(self):
        """write_frontmatter creates the CLAUDE.md if it doesn't exist yet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_md = Path(tmpdir) / "CLAUDE.md"
            self.assertFalse(claude_md.exists())

            write_frontmatter(claude_md, {"slug": "new", "status": "todo"})

            self.assertTrue(claude_md.exists())
            result = read_frontmatter(claude_md)
        self.assertEqual(result.get("slug"), "new")


if __name__ == "__main__":
    unittest.main()
