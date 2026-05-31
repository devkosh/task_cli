#!/usr/bin/env python3
"""
rebuild_readme.py — Regenerate the root README.md from task frontmatter.

Called by `tasks done` (step 6 of SEC-10) after outputs are confirmed.
Reads all */*/CLAUDE.md files, builds the Overview Table, Session Details,
and Final Outputs Archive sections, then rewrites README.md in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# === CONSTANTS ===

TASKS_ROOT: Path = Path(__file__).resolve().parent.parent
README_PATH: Path = TASKS_ROOT / "README.md"

SECTION_OVERVIEW = "## Overview of Tasks"
SECTION_SESSIONS = "## Session Details"
SECTION_ARCHIVE = "## Archive of Final Outputs"
SECTION_UPDATED = "<!-- last-updated -->"


# === HELPERS ===


def read_all_frontmatters() -> list[dict]:
    """Glob TASKS_ROOT for */*/CLAUDE.md files and parse each frontmatter; skip malformed."""
    raise NotImplementedError


def render_overview_table(frontmatters: list[dict]) -> str:
    """Build a Markdown table with columns: Session | Slug | Type | Status | Deliverables."""
    raise NotImplementedError


def render_session_details(frontmatters: list[dict]) -> str:
    """Build per-session Markdown sections listing tasks and their output files."""
    raise NotImplementedError


def render_archive(frontmatters: list[dict]) -> str:
    """Build the Final Outputs Archive section listing all registered output file paths."""
    raise NotImplementedError


def inject_sections(existing_readme: str, sections: dict[str, str]) -> str:
    """Replace named sections in README text; add missing sections before last-updated marker."""
    raise NotImplementedError


def update_last_updated(text: str) -> str:
    """Replace the <!-- last-updated --> marker value with today's date."""
    raise NotImplementedError


# === ENTRY POINT ===


def main() -> int:
    """Rebuild README.md in TASKS_ROOT from current task frontmatter; return 0 on success."""
    raise NotImplementedError


if __name__ == "__main__":
    import sys

    sys.exit(main())
