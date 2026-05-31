#!/usr/bin/env python3
"""
rebuild_readme.py — Regenerate the root README.md from task frontmatter.

Called by `tasks done` (step 6 of SEC-10) after outputs are confirmed.
Scans all */*/CLAUDE.md files, reads frontmatter, and rebuilds the
## Task Overview table. Replaces the section in-place or appends if absent.
Updates the Last updated: line at the bottom.
"""

from __future__ import annotations

import datetime
import io
import re
import sys
from pathlib import Path

# === CONSTANTS ===

TASKS_ROOT: Path = Path(__file__).resolve().parent.parent
README_PATH: Path = TASKS_ROOT / "README.md"

SECTION_HEADER = "## Task Overview"


# === FRONTMATTER READER (minimal, no external deps beyond ruamel.yaml) ===


def _read_frontmatter(claude_md_path: Path) -> dict:
    """Parse YAML frontmatter from a CLAUDE.md file; return {} on any failure."""
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.preserve_quotes = True

        if not claude_md_path.exists():
            return {}
        content = claude_md_path.read_text(encoding="utf-8")

        if not content.startswith("---\n"):
            return {}
        end_idx = content.find("\n---\n", 4)
        if end_idx == -1:
            return {}
        yaml_str = content[4:end_idx]
        result = yaml.load(io.StringIO(yaml_str))
        return dict(result) if result else {}
    except Exception:
        return {}


# === SECTION BUILDER ===


def _build_overview_table(rows: list[dict]) -> str:
    """Build a Markdown table: Session | Slug | Type | Status."""
    lines = [
        SECTION_HEADER,
        "",
        "| Session | Slug | Type | Status |",
        "|---------|------|------|--------|",
    ]
    for row in rows:
        session = str(row.get("session", ""))
        slug = str(row.get("slug", ""))
        task_type = str(row.get("type", ""))
        status = str(row.get("status", ""))
        lines.append(f"| {session} | {slug} | {task_type} | {status} |")
    lines.append("")
    return "\n".join(lines)


# === README SECTION INJECTOR ===


def _inject_overview(readme_text: str, new_section: str) -> str:
    """Replace existing ## Task Overview section in readme_text, or append it."""
    # Pattern: from the section header to the next ## heading (or end of file)
    pattern = re.compile(
        r"^## Task Overview\b.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    replacement = new_section + "\n"
    if pattern.search(readme_text):
        return pattern.sub(replacement, readme_text)
    # No existing section — append before last-updated line or at end
    if "Last updated:" in readme_text:
        readme_text = readme_text.rstrip()
        return readme_text + "\n\n" + new_section + "\n"
    return readme_text.rstrip() + "\n\n" + new_section + "\n"


def _update_last_updated(text: str) -> str:
    """Replace or append a 'Last updated: YYYY-MM-DD' line."""
    today = datetime.date.today().isoformat()
    pattern = re.compile(r"Last updated:.*", re.IGNORECASE)
    new_line = f"Last updated: {today}"
    if pattern.search(text):
        return pattern.sub(new_line, text)
    return text.rstrip() + f"\n\n{new_line}\n"


# === ENTRY POINT ===


def main() -> int:
    """Rebuild README.md from current task frontmatter; return 0 on success."""
    # 1. Collect all frontmatters
    rows: list[dict] = []
    for claude_md in sorted(TASKS_ROOT.glob("*/*/CLAUDE.md")):
        fm = _read_frontmatter(claude_md)
        if not fm:
            continue
        # Derive session and slug from path if not in frontmatter
        parts = claude_md.relative_to(TASKS_ROOT).parts  # (session, slug, "CLAUDE.md")
        if "session" not in fm and len(parts) >= 1:
            fm["session"] = parts[0]
        if "slug" not in fm and len(parts) >= 2:
            fm["slug"] = parts[1]
        rows.append(fm)

    # Sort by session descending, then slug ascending
    rows.sort(key=lambda r: (-int(r.get("session", "0")) if str(r.get("session", "")).isdigit() else 0,
                              str(r.get("slug", ""))))

    # 2. Build the table
    new_section = _build_overview_table(rows)

    # 3. Read existing README or start fresh
    if README_PATH.exists():
        readme_text = README_PATH.read_text(encoding="utf-8")
    else:
        readme_text = "# Task CLI\n\n"

    # 4. Inject section and update last-updated
    readme_text = _inject_overview(readme_text, new_section)
    readme_text = _update_last_updated(readme_text)

    # 5. Write back
    README_PATH.write_text(readme_text, encoding="utf-8")
    print(f"README.md updated ({len(rows)} task(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
