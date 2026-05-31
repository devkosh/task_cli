#!/usr/bin/env python3
"""
tasks.py — Single-file CLI orchestrating the full task lifecycle.

Usage:
    tasks new
    tasks work [<session/slug>]
    tasks review [<session/slug>]
    tasks done [<session/slug>]
    tasks status [--session DDMMYYYY] [--type TYPE] [--open]
    tasks transcribe [<session/slug>]
    tasks edit [<session/slug>]

Symlink to ~/.local/bin/tasks for global access:
    ln -sf $(pwd)/scripts/tasks.py ~/.local/bin/tasks
    chmod +x ~/.local/bin/tasks
"""

from __future__ import annotations

# === IMPORTS ===

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ruamel.yaml is the only hard runtime dependency (pip install ruamel.yaml)
# Import is deferred to read_frontmatter / write_frontmatter so the CLI
# can still print --help even if the package is not yet installed.

# === CONSTANTS ===

TASKS_ROOT: Path = Path(__file__).resolve().parent.parent
"""Absolute path to the repository root (one level above scripts/)."""

AI_CASCADE: list[str] = ["claude", "codex", "agy"]
"""Ordered list of AI CLI tools to try; first found wins."""

TASK_TYPES: list[str] = [
    "personnel",
    "reporting",
    "procurement",
    "presentation",
    "retro",
    "extraction",
    "planning",
]
"""Numbered type picker options shown during `tasks new`."""

STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for",
        "from", "has", "he", "in", "is", "it", "its", "of", "on",
        "or", "that", "the", "to", "was", "were", "will", "with",
        # Ukrainian stopwords (transliterated equivalents handled at runtime)
        "та", "і", "в", "на", "з", "до", "за", "що", "як",
        "про", "по", "у", "це", "він", "вона", "вони",
    }
)
"""Words stripped when generating a heuristic slug from task context."""

FRONTMATTER_KEYS_ORDER: list[str] = [
    "slug", "type", "status", "created", "session", "deliverables", "outputs",
]
"""Canonical key order preserved by ruamel.yaml round-trip writes."""

STATUS_ICONS: dict[str, str] = {
    "todo": "⬜",
    "in_progress": "🔄",
    "reviewing": "🔍",
    "done": "✅",
}
"""Terminal icons used by `tasks status` table renderer."""

CLAUDE_MD_TEMPLATE: str = """\
---
slug: {slug}
type: {type}
status: todo
created: {created}
session: {session}
deliverables: []
outputs: []
---

# {slug}

## Goal
{goal}

## Context
See `raw/context.md`.

## Deliverables
<!-- List expected output files here, e.g.:
- slides_compressed_v1.md
-->

## Iteration Log
<!-- Auto-updated by `tasks review` -->
"""
"""Template for the per-task CLAUDE.md written during `tasks new`."""


# === FRONTMATTER I/O (ruamel.yaml round-trip) ===


def read_frontmatter(claude_md_path: Path) -> dict:
    """Parse YAML frontmatter from a CLAUDE.md file; return empty dict on failure."""
    raise NotImplementedError


def write_frontmatter(claude_md_path: Path, data: dict) -> None:
    """Write updated frontmatter back to CLAUDE.md preserving body text and comments."""
    raise NotImplementedError


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split raw file text into (yaml_block, body_text); return ('', text) if no frontmatter."""
    raise NotImplementedError


# === TASK RESOLUTION (SEC-5) ===


def list_tasks(filter_session: Optional[str] = None, filter_type: Optional[str] = None) -> list[Path]:
    """Glob TASKS_ROOT for all */*/CLAUDE.md paths, optionally filtered by session or type."""
    raise NotImplementedError


def pick_task(tasks: list[Path]) -> Optional[Path]:
    """Interactively select a task via fzf; fall back to numbered list if fzf absent."""
    raise NotImplementedError


def find_task(arg: Optional[str] = None) -> Optional[Path]:
    """Resolve a task from an optional CLI argument (exact path, session/slug, or picker)."""
    raise NotImplementedError


def _fzf_available() -> bool:
    """Return True if fzf is on PATH."""
    raise NotImplementedError


def _numbered_list_pick(items: list[str], prompt: str = "Select: ") -> Optional[int]:
    """Print a numbered list and read a 1-based integer choice from stdin; return None on cancel."""
    raise NotImplementedError


# === SLUG & TYPE HELPERS (SEC-7) ===


def heuristic_slug(text: str) -> str:
    """Derive a kebab-case slug from free text by stripping stopwords and joining 3-4 keywords."""
    raise NotImplementedError


def pick_task_type() -> str:
    """Present the TASK_TYPES numbered picker; return the chosen type string."""
    raise NotImplementedError


def confirm_slug(suggested: str) -> str:
    """Prompt user to confirm, edit, or AI-regenerate a suggested slug; return final slug."""
    raise NotImplementedError


# === AI CASCADE (SEC-6) ===


def find_ai_cli() -> Optional[str]:
    """Return the first available AI CLI from AI_CASCADE via shutil.which(), or None."""
    raise NotImplementedError


def run_ai_gen(prompt: str, task_dir: Path) -> str:
    """Run AI CLI non-interactively with prompt; capture and return stdout."""
    raise NotImplementedError


def run_ai_work(task_dir: Path) -> int:
    """Launch AI CLI in yolo/autonomous work mode inside task_dir; inherit terminal; return exit code."""
    raise NotImplementedError


def run_ai_review(task_dir: Path) -> int:
    """Launch AI CLI in yolo/autonomous review mode inside task_dir; inherit terminal; return exit code."""
    raise NotImplementedError


def _build_review_prompt(task_dir: Path, iteration: int) -> str:
    """Construct the review prompt string from task.md and the latest work iteration log."""
    raise NotImplementedError


# === ITERATION & VERSIONING (SEC-8, SEC-9) ===


def next_iteration(task_dir: Path) -> int:
    """Scan task_dir/iterations/ and return the next iteration number (1 if empty)."""
    raise NotImplementedError


def versioned_deliverable(name: str, n: int) -> str:
    """Replace _vN suffix in name with _v{n}; append _v{n} if no suffix exists."""
    raise NotImplementedError


def log_work(task_dir: Path, iteration: int, ai_cli: str, exit_code: int) -> Path:
    """Create and return path of iterations/<n>_work_<ts>.md stub; append summary after AI exit."""
    raise NotImplementedError


def log_review(task_dir: Path, iteration: int, passed: bool, failure_notes: str = "") -> Path:
    """Create and return path of iterations/<n>_review_<ts>.md; record pass/fail + notes."""
    raise NotImplementedError


def update_context_log(task_dir: Path, iteration: int, summary: str) -> None:
    """Rewrite the '## Iteration Log' section in raw/context.md with the new iteration entry."""
    raise NotImplementedError


# === OUTPUT DETECTION & README (SEC-10) ===


def detect_outputs(task_dir: Path, iteration: int) -> list[Path]:
    """Parse ## Deliverables from task.md, derive versioned filenames, return those that exist."""
    raise NotImplementedError


def confirm_outputs(found: list[Path], missing: list[str]) -> bool:
    """Print detected/missing outputs and ask user to confirm before registering."""
    raise NotImplementedError


def rebuild_readme() -> int:
    """Run scripts/rebuild_readme.py as a subprocess; return its exit code."""
    raise NotImplementedError


# === STATUS TABLE (SEC-11) ===


def render_status_table(
    tasks: list[Path],
    filter_open: bool = False,
) -> None:
    """Print a formatted table of task status icons, slugs, types, sessions, and deliverables."""
    raise NotImplementedError


# === TRANSCRIPTION HELPERS (SEC-12) ===


def find_audio_files(task_dir: Path) -> list[Path]:
    """Return raw/audio/ files not yet transcribed (no matching .txt in transcriptions/)."""
    raise NotImplementedError


def run_transcription(audio_file: Path, task_dir: Path) -> int:
    """Run mlx_whisper sequentially on a single audio file; return exit code."""
    raise NotImplementedError


# === GIT HELPERS ===


def git_stage_and_commit(task_dir: Path, message: str) -> int:
    """Stage task_dir contents and create a git commit in TASKS_ROOT; return exit code."""
    raise NotImplementedError


# === COMMAND IMPLEMENTATIONS ===


def cmd_new(args: argparse.Namespace) -> int:
    """Orchestrate full new-task flow: context capture → AI brief → slug confirm → folder creation.

    Steps (SEC-7):
        1. Collect multi-line context (Ctrl+D to finish) → save raw/context.md
        2. AI generates structured task.md from context
        3. Compute heuristic_slug(); call confirm_slug()
        4. pick_task_type()
        5. Create folder: DDMMYYYY/slug/{raw/audio,raw/files,transcriptions,iterations}/
        6. Write CLAUDE.md with YAML frontmatter
        7. Write raw/context.md
        8. Write task.md (AI output)
        9. Offer 'tasks work <session/slug>?'
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_work(args: argparse.Namespace) -> int:
    """Run an AI work session for a task, tracking iteration and updating status.

    Steps (SEC-8):
        1. Resolve task via find_task(args.task)
        2. status: todo → in_progress via write_frontmatter
        3. next_iteration(task_dir) → N
        4. versioned_deliverable() for each deliverable in frontmatter
        5. log_work() creates iterations/<n>_work_<ts>.md stub
        6. find_ai_cli() → run_ai_work(task_dir)
        7. Append summary to iteration log on exit
        8. Prompt 'Run review now? [Y/n]' → optionally call cmd_review
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_review(args: argparse.Namespace) -> int:
    """Run an AI review session, record pass/fail, and route to done or back to work.

    Steps (SEC-9):
        1. Resolve task via find_task(args.task)
        2. status: in_progress → reviewing via write_frontmatter
        3. Determine N = next_iteration(task_dir) - 1
           NOTE: review belongs to the SAME iteration as the preceding work session.
           After cmd_work writes <N>_work_<ts>.md, next_iteration() returns N+1,
           so review must use N+1-1 = N to produce paired <N>_review_<ts>.md logs.
           Do NOT call next_iteration() naively (would create (N+1)_review mismatch).
        4. log_review() creates iterations/<n>_review_<ts>.md
        5. _build_review_prompt(task_dir, N) → find_ai_cli() → run_ai_review(task_dir)
        6. Prompt 'Review passed? [y/n]'
           - y: update_context_log() → offer 'tasks done'
           - n: collect failure notes → append to review log → offer 'tasks work'
              (cmd_work will then call next_iteration() to get N+1 for the next cycle)
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_done(args: argparse.Namespace) -> int:
    """Finalize a task: detect outputs, update frontmatter, rebuild README, offer commit.

    Steps (SEC-10):
        1. Resolve task via find_task(args.task)
        2. status: reviewing → done (or in_progress → done quick path)
        3. detect_outputs() → confirm_outputs()
        4. Append confirmed paths to outputs: via write_frontmatter
        5. rebuild_readme()
        6. Prompt 'Commit? [y/N]' → git_stage_and_commit()
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_status(args: argparse.Namespace) -> int:
    """Print a status table for all tasks, optionally filtered by session, type, or open status.

    Steps (SEC-11):
        1. list_tasks(filter_session=args.session, filter_type=args.type)
        2. render_status_table(tasks, filter_open=args.open)
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Transcribe audio files in a task's raw/audio/ dir using mlx_whisper (sequential).

    Steps (SEC-12):
        1. Resolve task via find_task(args.task)
        2. find_audio_files() — skip already-transcribed
        3. run_transcription() for each file sequentially
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


def cmd_edit(args: argparse.Namespace) -> int:
    """Open task.md in $EDITOR (fallback: open -t on macOS).

    Steps (SEC-12):
        1. Resolve task via find_task(args.task)
        2. Open task_dir/task.md in os.environ['EDITOR'] or subprocess 'open -t'
    Returns 0 on success, non-zero on error.
    """
    raise NotImplementedError


# === ARGUMENT PARSER ===


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level ArgumentParser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="tasks",
        description="Local task lifecycle orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # tasks new
    subparsers.add_parser("new", help="Create a new task interactively")

    # tasks work [task]
    work = subparsers.add_parser("work", help="Run an AI work session for a task")
    work.add_argument("task", nargs="?", help="session/slug or path (optional — triggers picker)")

    # tasks review [task]
    review = subparsers.add_parser("review", help="Run an AI review session for a task")
    review.add_argument("task", nargs="?", help="session/slug or path (optional — triggers picker)")

    # tasks done [task]
    done = subparsers.add_parser("done", help="Finalize a task and register outputs")
    done.add_argument("task", nargs="?", help="session/slug or path (optional — triggers picker)")

    # tasks status
    status = subparsers.add_parser("status", help="Print task status table")
    status.add_argument("--session", metavar="DDMMYYYY", help="Filter by session folder name")
    status.add_argument("--type", dest="type", choices=TASK_TYPES, help="Filter by task type")
    status.add_argument("--open", action="store_true", help="Show only non-done tasks")

    # tasks transcribe [task]
    transcribe = subparsers.add_parser("transcribe", help="Transcribe audio files with mlx_whisper")
    transcribe.add_argument("task", nargs="?", help="session/slug or path (optional — triggers picker)")

    # tasks edit [task]
    edit = subparsers.add_parser("edit", help="Open task.md in $EDITOR")
    edit.add_argument("task", nargs="?", help="session/slug or path (optional — triggers picker)")

    return parser


# === ENTRY POINT ===


def main() -> None:
    """Parse arguments and dispatch to the appropriate cmd_* function."""
    parser = build_parser()
    args = parser.parse_args()

    dispatch: dict[str, object] = {
        "new": cmd_new,
        "work": cmd_work,
        "review": cmd_review,
        "done": cmd_done,
        "status": cmd_status,
        "transcribe": cmd_transcribe,
        "edit": cmd_edit,
    }

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = dispatch.get(args.command)
    if handler is None:
        parser.error(f"Unknown command: {args.command!r}")

    sys.exit(handler(args))  # type: ignore[call-arg]


if __name__ == "__main__":
    main()
