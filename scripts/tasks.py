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
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ruamel.yaml is the only hard runtime dependency (pip install ruamel.yaml)
# Import is deferred to read_frontmatter / write_frontmatter so the CLI
# can still print --help even if the package is not yet installed.

# === CONSTANTS ===

TASKS_ROOT: Path = Path(os.environ["TASKS_ROOT"]) if "TASKS_ROOT" in os.environ else Path(__file__).resolve().parent.parent
"""Absolute path to the repository root. Override via TASKS_ROOT env var."""

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
        "a", "an", "the", "and", "or", "for", "of", "to", "in", "is",
        "it", "this", "that", "with", "from", "on", "at", "by", "be",
        "was", "are", "as", "its", "i", "we", "they", "he", "she",
        "my", "our", "their", "about", "have", "has", "had", "need",
        "needs", "some", "any", "all", "not", "no", "can", "will",
        "do", "done", "did", "get", "got", "make", "made", "take",
        "taken", "using", "use", "used", "let", "into", "up", "out",
        "if", "but", "so", "than", "then", "when", "also", "just",
        "more", "new", "other", "see", "way", "how", "what", "which",
        "who", "his", "her", "them", "been", "would", "could",
        "should", "may", "might", "must", "shall", "own", "via",
        "per", "after", "before", "during", "each", "every", "both",
        "few", "here", "there", "only", "over", "under", "again",
        "further", "once", "same", "such", "too", "very",
        "s", "t", "re", "ll", "ve", "d", "m",
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

NEW_TASK_PROMPT: str = """\
You are a task planner. Based on the following context, generate a structured task.md file.

Context:
{context}

Output a markdown file with these sections:
# Task Title

## Goal
One sentence describing what needs to be accomplished.

## Context
Brief background.

## Deliverables
- item_v1.md — description

## Notes
Any important constraints or references.
"""
"""Prompt template passed to the AI CLI during `tasks new` to generate task.md."""

_FALLBACK_TASK_TEMPLATE: str = """\
# Task

## Goal
Describe the goal here.

## Context
See `raw/context.md`.

## Deliverables
- output_v1.md — main deliverable

## Notes
(none)
"""
"""Fallback task.md used when no AI CLI is available or AI generation fails."""


# === FRONTMATTER I/O (ruamel.yaml round-trip) ===


def read_frontmatter(claude_md_path: Path) -> dict:
    """Parse YAML frontmatter from a CLAUDE.md file; return empty dict on failure."""
    try:
        from ruamel.yaml import YAML  # deferred — keep --help working without ruamel
        yaml = YAML()
        yaml.preserve_quotes = True

        if not claude_md_path.exists():
            return {}
        content = claude_md_path.read_text(encoding="utf-8")
        yaml_str, _ = _split_frontmatter(content)
        if not yaml_str:
            return {}
        import io
        result = yaml.load(io.StringIO(yaml_str))
        return dict(result) if result else {}
    except Exception:
        return {}


def write_frontmatter(claude_md_path: Path, data: dict) -> None:
    """Write updated frontmatter back to CLAUDE.md preserving body text and comments."""
    from ruamel.yaml import YAML  # deferred — keep --help working without ruamel
    import io

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False

    # Load existing body if file exists
    body = ""
    if claude_md_path.exists():
        content = claude_md_path.read_text(encoding="utf-8")
        _, body = _split_frontmatter(content)

    # Serialise frontmatter
    stream = io.StringIO()
    yaml.dump(data, stream)
    fm_str = stream.getvalue()

    # Ensure fm_str ends with a newline so the closing --- sits on its own line
    if not fm_str.endswith("\n"):
        fm_str += "\n"
    claude_md_path.write_text(f"---\n{fm_str}---\n{body}", encoding="utf-8")


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split raw file text into (yaml_block, body_text); return ('', text) if no frontmatter."""
    if not text.startswith("---\n"):
        return ("", text)
    # Find the closing ---
    end_idx = text.find("\n---\n", 4)
    if end_idx == -1:
        return ("", text)
    yaml_str = text[4:end_idx]          # content between the two ---
    body = text[end_idx + 5:]           # content after closing ---\n
    return (yaml_str, body)


# === TASK RESOLUTION (SEC-5) ===


def list_tasks(
    filter_session: Optional[str] = None,
    filter_type: Optional[str] = None,
    filter_status: Optional[str] = None,
) -> list[Path]:
    """Glob TASKS_ROOT for all */*/CLAUDE.md paths, optionally filtered by session, type, or status."""
    task_dirs: list[Path] = []
    for claude_md in TASKS_ROOT.glob("*/*/CLAUDE.md"):
        task_dir = claude_md.parent.relative_to(TASKS_ROOT)
        # Filter by session (first path component)
        if filter_session is not None and task_dir.parts[0] != filter_session:
            continue
        # Filter by type or status via frontmatter (silently skip if NotImplementedError)
        if filter_type is not None or filter_status is not None:
            try:
                fm = read_frontmatter(claude_md)
                if filter_type is not None and fm.get("type") != filter_type:
                    continue
                if filter_status is not None and fm.get("status") != filter_status:
                    continue
            except (NotImplementedError, Exception):
                continue
        task_dirs.append(task_dir)
    return sorted(task_dirs)


def pick_task(tasks: list[Path]) -> Optional[Path]:
    """Interactively select a task via fzf; fall back to numbered list if fzf absent."""
    if not tasks:
        print("No tasks found.")
        sys.exit(1)
    if len(tasks) == 1:
        return tasks[0]
    # Build display strings like "31052026/video-compress"
    labels = [str(t) for t in tasks]
    if _fzf_available():
        input_text = "\n".join(labels) + "\n"
        try:
            result = subprocess.run(
                ["fzf", "--prompt", "Select task: "],
                input=input_text,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                print("No task selected.")
                sys.exit(1)
            chosen = result.stdout.strip()
            return Path(chosen)
        except Exception as exc:
            print(f"fzf error: {exc}. Falling back to numbered list.")
    # Fallback: numbered list
    idx = _numbered_list_pick(labels)
    if idx is None:
        print("No task selected.")
        sys.exit(1)
    return tasks[idx]


def find_task(arg: Optional[str] = None, session_override: Optional[str] = None) -> Optional[Path]:
    """Resolve a task from an optional CLI argument (exact path, session/slug, or picker)."""
    # If arg looks like an exact DDMMYYYY/slug path and the directory exists, use it directly
    if arg is not None:
        candidate = TASKS_ROOT / arg
        if candidate.is_dir():
            return Path(arg)
    # Otherwise, launch interactive picker
    tasks = list_tasks(filter_session=session_override)
    return pick_task(tasks)


def _fzf_available() -> bool:
    """Return True if fzf is on PATH."""
    return shutil.which("fzf") is not None


def _numbered_list_pick(items: list[str], prompt: str = "Select: ") -> Optional[int]:
    """Print a numbered list and read a 1-based integer choice from stdin; return None on cancel."""
    for i, item in enumerate(items, start=1):
        print(f"  {i}. {item}")
    while True:
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.lower() in ("", "q", "quit", "cancel"):
            return None
        try:
            choice = int(raw)
        except ValueError:
            print(f"  Invalid input. Enter a number between 1 and {len(items)}, or 'q' to cancel.")
            continue
        if 1 <= choice <= len(items):
            return choice - 1  # Return 0-based index
        print(f"  Out of range. Enter a number between 1 and {len(items)}, or 'q' to cancel.")


# === SLUG & TYPE HELPERS (SEC-7) ===


def heuristic_slug(text: str) -> str:
    """Derive a kebab-case slug from free text by stripping stopwords and joining 3-4 keywords."""
    # Lowercase
    lowered = text.lower()
    # Remove punctuation — keep alphanumeric, spaces, and Ukrainian letters
    cleaned = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    # Split into words
    words = cleaned.split()
    # Remove stopwords
    keywords = [w for w in words if w not in STOPWORDS]
    # Take first 3-4 non-stopword words
    selected = keywords[:4]
    if not selected:
        return "task"
    return "-".join(selected)


def pick_task_type(preset: Optional[str] = None) -> str:
    """Present the TASK_TYPES numbered picker; return the chosen type string."""
    if preset is not None and preset in TASK_TYPES:
        return preset
    print("Task type:")
    for i, t in enumerate(TASK_TYPES, start=1):
        print(f"  {i}. {t}")
    while True:
        try:
            raw = input("Select type (number): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return TASK_TYPES[0]
        try:
            choice = int(raw)
        except ValueError:
            print(f"  Enter a number between 1 and {len(TASK_TYPES)}.")
            continue
        if 1 <= choice <= len(TASK_TYPES):
            return TASK_TYPES[choice - 1]
        print(f"  Out of range. Enter a number between 1 and {len(TASK_TYPES)}.")


def confirm_slug(suggested: str) -> str:
    """Prompt user to confirm, edit, or AI-regenerate a suggested slug; return final slug."""
    print(f"Suggested slug: {suggested}")
    try:
        answer = input("[Enter=confirm / type new slug / 'ai'=regenerate]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return suggested
    if answer == "":
        return suggested
    if answer.lower() == "ai":
        # Regeneration placeholder — context not available here
        return suggested + "-v2"
    # User typed a custom slug
    return answer.replace(" ", "-")


# === AI CASCADE (SEC-6) ===


def find_ai_cli() -> Optional[str]:
    """Return the first available AI CLI from AI_CASCADE via shutil.which(), or None."""
    for cli in AI_CASCADE:
        if shutil.which(cli) is not None:
            return cli
    return None


def run_ai_gen(prompt: str, task_dir: Path) -> str:
    """Run AI CLI non-interactively with prompt; capture and return stdout."""
    cli = find_ai_cli()
    if cli is None:
        raise RuntimeError("No AI CLI found (tried: claude, codex, agy)")

    if cli == "claude":
        cmd = ["claude", "--print", "-p", prompt]
    elif cli == "codex":
        cmd = ["codex", "run", "--no-interactive", prompt]
    else:  # agy
        cmd = ["agy", prompt]

    result = subprocess.run(cmd, cwd=task_dir, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"AI gen failed ({cli}): {result.stderr[:500]}")
    return result.stdout.strip()


def run_ai_work(task_dir: Path) -> int:
    """Launch AI CLI in yolo/autonomous work mode inside task_dir; inherit terminal; return exit code."""
    work_prompt = _build_work_prompt(task_dir)
    cli = find_ai_cli()
    if cli is None:
        print("Error: No AI CLI found (tried: claude, codex, agy)")
        sys.exit(1)

    if cli == "claude":
        cmd = ["claude", "--dangerously-skip-permissions", "-p", work_prompt]
    elif cli == "codex":
        cmd = ["codex", "run", work_prompt]
    else:  # agy
        cmd = ["agy", work_prompt]

    result = subprocess.run(cmd, cwd=task_dir)
    return result.returncode


def run_ai_review(task_dir: Path) -> int:
    """Launch AI CLI in yolo/autonomous review mode inside task_dir; inherit terminal; return exit code."""
    review_prompt = _build_review_prompt(task_dir, iteration=0)
    cli = find_ai_cli()
    if cli is None:
        print("Error: No AI CLI found (tried: claude, codex, agy)")
        sys.exit(1)

    if cli == "claude":
        cmd = ["claude", "--dangerously-skip-permissions", "-p", review_prompt]
    elif cli == "codex":
        cmd = ["codex", "run", review_prompt]
    else:  # agy
        cmd = ["agy", review_prompt]

    result = subprocess.run(cmd, cwd=task_dir)
    return result.returncode


def _build_work_prompt(task_dir: Path) -> str:
    """Construct the yolo work prompt string."""
    return (
        f"Read ./task.md and execute everything described in it. No approval needed. "
        f"Produce all ## Deliverables listed. When done, create AGENT_RESULT.md with a brief summary of what was produced.\n"
        f"Work directory: {task_dir.name}"
    )


def _build_review_prompt(task_dir: Path, iteration: int) -> str:
    """Construct the review prompt string from task.md and the latest work iteration log."""
    return (
        "Read ./task.md and ./AGENT_RESULT.md. Review the deliverables produced against the task requirements.\n"
        "Ask at most 5 clarifying questions. After corrections, confirm all deliverables are present and correct."
    )


# === ITERATION & VERSIONING (SEC-8, SEC-9) ===


def next_iteration(task_dir: Path) -> int:
    """Scan task_dir/iterations/ and return the next iteration number (1 if empty)."""
    iterations_dir = task_dir / "iterations"
    if not iterations_dir.exists():
        return 1
    max_n = 0
    for f in iterations_dir.glob("*.md"):
        m = re.match(r'^(\d+)_', f.name)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1 if max_n > 0 else 1


def versioned_deliverable(name: str, n: int) -> str:
    """Replace _vN suffix in name with _v{n}; append _v{n} if no suffix exists."""
    if re.search(r'_v\d+', name):
        return re.sub(r'_v\d+', f'_v{n}', name)
    p = Path(name)
    return p.stem + f'_v{n}' + p.suffix


def log_work(task_dir: Path, n: int) -> Path:
    """Create and return path of iterations/<n>_work_<ts>.md stub."""
    iterations_dir = task_dir / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = iterations_dir / f"{n}_work_{ts}.md"
    date_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    log_path.write_text(
        f"# Work Session — Iteration {n}\n"
        f"Date: {date_str}\n"
        f"Task: {task_dir.name}\n"
        f"\n"
        f"## Summary\n"
        f"(filled after session)\n"
        f"\n"
        f"## Files Produced\n"
        f"(filled after session)\n",
        encoding="utf-8",
    )
    return log_path


def log_review(task_dir: Path, n: int) -> Path:
    """Create and return path of iterations/<n>_review_<ts>.md stub."""
    iterations_dir = task_dir / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = iterations_dir / f"{n}_review_{ts}.md"
    date_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    log_path.write_text(
        f"# Review Session — Iteration {n}\n"
        f"Date: {date_str}\n"
        f"Task: {task_dir.name}\n"
        f"\n"
        f"## Review Notes\n"
        f"(filled during session)\n"
        f"\n"
        f"## Outcome\n"
        f"(passed / failed — filled after session)\n",
        encoding="utf-8",
    )
    return log_path


def update_context_log(task_dir: Path, n: int) -> None:
    """Rewrite the '## Iteration Log' section in raw/context.md with all iteration entries."""
    context_path = task_dir / "raw" / "context.md"
    content = context_path.read_text(encoding="utf-8") if context_path.exists() else ""

    # Find all iteration files grouped by iteration number
    iterations_dir = task_dir / "iterations"
    iter_files: dict[int, list[Path]] = {}
    if iterations_dir.exists():
        for f in sorted(iterations_dir.glob("*.md")):
            m = re.match(r'^(\d+)_', f.name)
            if m:
                num = int(m.group(1))
                iter_files.setdefault(num, []).append(f)

    # Build the log section
    log_lines = ["## Iteration Log\n"]
    for num in sorted(iter_files):
        log_lines.append(f"\n### Iteration {num}\n")
        for f in iter_files[num]:
            log_lines.append(f"- [{f.name}](iterations/{f.name})\n")
    log_section = "".join(log_lines)

    # Replace or append
    if "## Iteration Log" in content:
        content = re.sub(r'## Iteration Log.*$', log_section, content, flags=re.DOTALL)
    else:
        content = content.rstrip() + "\n\n" + log_section

    context_path.write_text(content, encoding="utf-8")


# === OUTPUT DETECTION & README (SEC-10) ===


def detect_outputs(task_dir: Path, n: int) -> list[str]:
    """Parse ## Deliverables from task.md, apply versioning, return list of versioned filenames.

    Does NOT filter by on-disk existence — returns all declared deliverables.
    Existence checks are done in cmd_done (step 5–6).
    """
    task_md = task_dir / "task.md"
    if not task_md.exists():
        return []

    lines = task_md.read_text(encoding="utf-8").splitlines()
    in_section = False
    results: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == "## Deliverables":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## "):
                # Next section header — stop
                break
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                # Extract filename part: take text before " — " separator (em-dash)
                if " — " in item:
                    name = item.split(" — ", 1)[0].strip()
                else:
                    name = item.strip()
                if name:
                    results.append(versioned_deliverable(name, n))

    return results


def confirm_outputs(outputs: list[str]) -> list[str]:
    """Print detected outputs and ask user to confirm or provide a custom list.

    Returns:
        Full list if confirmed, custom list if user provides one, [] if none declared.
    """
    if not outputs:
        print("No outputs declared in task.md.")
        return []

    print("Detected outputs:")
    for i, name in enumerate(outputs, start=1):
        print(f"  {i}. {name}")

    try:
        answer = input("Confirm? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return outputs

    if answer in ("", "y", "yes"):
        return outputs

    # User declined — ask for manual list
    try:
        raw = input("Enter filenames (comma-separated): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def rebuild_readme() -> None:
    """Run scripts/rebuild_readme.py as a subprocess; warn on failure but do not crash."""
    result = subprocess.run(
        ["python3", str(TASKS_ROOT / "scripts" / "rebuild_readme.py")],
        cwd=TASKS_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠ README rebuild failed: {result.stderr[:200]}")


# === STATUS TABLE (SEC-11) ===


def render_status_table(
    tasks: list[Path],
    filter_open: bool = False,
) -> None:
    """Print a formatted table of task status icons, slugs, types, sessions, and deliverables."""
    # Sort: session descending, then slug ascending
    sorted_tasks = sorted(tasks, key=lambda t: (-int(t.parts[0]) if t.parts[0].isdigit() else 0, t.parts[1] if len(t.parts) > 1 else ""))

    # Column widths (chars, emoji counts as 2 so icon rows use ljust(width - 1))
    W_STATUS = 14   # header "STATUS" fits in 14; data row has emoji → ljust(13)
    W_SESSION = 10
    W_SLUG = 24
    W_TYPE = 16

    # Header row (no emoji, full ljust)
    header = (
        "STATUS".ljust(W_STATUS)
        + "SESSION".ljust(W_SESSION)
        + "SLUG".ljust(W_SLUG)
        + "TYPE".ljust(W_TYPE)
    )
    separator = "─" * (W_STATUS + W_SESSION + W_SLUG + W_TYPE)
    print(header)
    print(separator)

    if not sorted_tasks:
        print("No tasks found.")
        print(f"\n0 task(s)")
        return

    for task_rel in sorted_tasks:
        parts = task_rel.parts
        session = parts[0] if len(parts) > 0 else ""
        slug = parts[1] if len(parts) > 1 else str(task_rel)

        fm = read_frontmatter(TASKS_ROOT / task_rel / "CLAUDE.md")
        status = fm.get("status", "unknown")
        task_type = fm.get("type", "")

        icon = STATUS_ICONS.get(status, "❓")
        # Build status cell: icon + space + status name, padded
        # Emoji counts as 2 chars in terminal → reduce ljust by 1
        status_cell = f"{icon} {status}"
        row = (
            status_cell.ljust(W_STATUS - 1)
            + session.ljust(W_SESSION)
            + slug.ljust(W_SLUG)
            + task_type.ljust(W_TYPE)
        )
        print(row)

    print(f"\n{len(sorted_tasks)} task(s)")


# === TRANSCRIPTION HELPERS (SEC-12) ===


def find_audio_files(task_dir: Path) -> list[Path]:
    """Return raw/audio/ files not yet transcribed (no matching .md in transcriptions/)."""
    audio_dir = task_dir / "raw" / "audio"
    trans_dir = task_dir / "transcriptions"
    extensions = ("*.ogg", "*.mp3", "*.m4a", "*.wav", "*.flac")
    candidates: list[Path] = []
    for pattern in extensions:
        candidates.extend(audio_dir.glob(pattern))
    result: list[Path] = []
    for audio_file in candidates:
        md_path = trans_dir / (audio_file.stem + ".md")
        if not md_path.exists():
            result.append(audio_file)
    return sorted(result)


def run_transcription(audio_file: Path, task_dir: Path) -> Path:
    """Run mlx_whisper sequentially on a single audio file; return path to output .md."""
    output_dir = task_dir / "transcriptions"
    output_dir.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "mlx_whisper", str(audio_file),
            "--model", "mlx-community/whisper-medium-mlx",
            "--language", "uk",
            "--output_format", "txt",
            "--output_dir", str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠ Transcription failed for {audio_file.name}: {result.stderr[:200]}")
        return output_dir / (audio_file.stem + ".txt")

    # Rename .txt → .md and add frontmatter
    txt_path = output_dir / (audio_file.stem + ".txt")
    md_path = output_dir / (audio_file.stem + ".md")
    if txt_path.exists():
        content = txt_path.read_text()
        frontmatter = (
            f"---\n"
            f"source: {audio_file.name}\n"
            f"date: {datetime.datetime.now().strftime('%Y-%m-%d')}\n"
            f"model: mlx-community/whisper-medium-mlx\n"
            f"---\n\n"
        )
        md_path.write_text(frontmatter + content)
        txt_path.unlink()  # remove .txt, keep .md
    print(f"✓ Transcribed: {audio_file.name} → {md_path.name}")
    return md_path


# === GIT HELPERS ===


def git_stage_and_commit(task_dir: Path) -> None:
    """Stage task_dir contents and README.md, then commit with 'feat({slug}): done'."""
    slug = f"{task_dir.parent.name}/{task_dir.name}"  # e.g. "31052026/video-compress"
    subprocess.run(["git", "add", str(task_dir)], cwd=TASKS_ROOT)
    subprocess.run(["git", "add", "README.md"], cwd=TASKS_ROOT, check=False)
    result = subprocess.run(
        ["git", "commit", "-m", f"feat({slug}): done"],
        cwd=TASKS_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"✓ Committed: feat({slug}): done")
    else:
        print(f"⚠ Commit failed: {result.stderr[:200]}")


# === COMMAND IMPLEMENTATIONS ===


def create_task_folder(task_dir: Path) -> None:
    """Create the canonical task folder structure under task_dir."""
    for sub in [
        task_dir,
        task_dir / "raw" / "audio",
        task_dir / "raw" / "files",
        task_dir / "transcriptions",
        task_dir / "iterations",
    ]:
        sub.mkdir(parents=True, exist_ok=True)


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
    # 1. Determine session
    session: str = getattr(args, "session", None) or datetime.datetime.now().strftime("%d%m%Y")

    print(f"\n=== tasks new (session: {session}) ===\n")

    # 2. Collect multi-line context
    print("Describe the task (Ctrl+D when done):")
    try:
        context_text = sys.stdin.read()
    except KeyboardInterrupt:
        print()
        return 1

    if not context_text.strip():
        print("No context provided. Aborting.")
        return 1

    # 3. Generate task.md via AI (with graceful fallback)
    task_md_content: str
    try:
        task_md_content = run_ai_gen(NEW_TASK_PROMPT.format(context=context_text), TASKS_ROOT)
    except RuntimeError as exc:
        print(f"  (AI generation unavailable: {exc})")
        print("  Using fallback task template.")
        task_md_content = _FALLBACK_TASK_TEMPLATE

    # 4. Heuristic slug → confirm
    slug = heuristic_slug(context_text)
    slug = confirm_slug(slug)

    # 5. Pick task type
    preset_type: Optional[str] = getattr(args, "type", None)
    task_type = pick_task_type(preset_type)

    # 6. Build task directory
    task_dir = TASKS_ROOT / session / slug

    # 7. Create folder structure
    create_task_folder(task_dir)

    # 8. Write raw/context.md
    (task_dir / "raw" / "context.md").write_text(context_text, encoding="utf-8")

    # 9. Write task.md
    (task_dir / "task.md").write_text(task_md_content, encoding="utf-8")

    # 10. Write CLAUDE.md with YAML frontmatter
    today_iso = datetime.datetime.now().strftime("%Y-%m-%d")
    fm_data = {
        "slug": slug,
        "type": task_type,
        "status": "todo",
        "created": today_iso,
        "session": session,
        "deliverables": [],
        "outputs": [],
    }
    write_frontmatter(task_dir / "CLAUDE.md", fm_data)
    # Append markdown body after frontmatter
    existing = (task_dir / "CLAUDE.md").read_text(encoding="utf-8")
    _, body = _split_frontmatter(existing)
    if not body.strip():
        # Write the body section
        body_text = f"\n# {slug}\n\nTask created by `tasks new`.\n"
        fm_raw, _ = _split_frontmatter(existing)
        if not fm_raw.endswith("\n"):
            fm_raw += "\n"
        (task_dir / "CLAUDE.md").write_text(
            f"---\n{fm_raw}---\n{body_text}", encoding="utf-8"
        )

    print(f"\n✓ Task created: {session}/{slug}\n")

    # 11. Offer to start working
    try:
        answer = input("Run tasks work now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer in ("", "y", "yes"):
        args.task = f"{session}/{slug}"
        try:
            return cmd_work(args)
        except NotImplementedError:
            print("  (tasks work is not yet implemented — run it manually)")
            return 0

    return 0


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
    # 1. Resolve task
    task_rel = find_task(getattr(args, 'task', None))
    task_dir = TASKS_ROOT / task_rel

    # 2. Read frontmatter and update status todo → in_progress
    fm = read_frontmatter(task_dir / "CLAUDE.md")
    if fm.get("status") == "todo":
        fm["status"] = "in_progress"
        write_frontmatter(task_dir / "CLAUDE.md", fm)

    # 3. Get next iteration number
    n = next_iteration(task_dir)

    # 4. Get versioned deliverables
    deliverables = fm.get("deliverables", [])
    versioned = [versioned_deliverable(d, n) for d in deliverables]

    # 5. Create iteration log stub
    log_path = log_work(task_dir, n)

    # 6. Print header
    print(f"\n=== tasks work: {task_dir} (iteration {n}) ===\n")
    if versioned:
        print(f"Target outputs: {versioned}\n")

    # 7. Find AI CLI
    cli = find_ai_cli()
    if cli is None:
        print("Error: No AI CLI found (tried: claude, codex, agy). Install one to run work sessions.")
        sys.exit(1)

    # 8. Run work session
    run_ai_work(task_dir)

    # 9. Append summary to iteration log
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n---\nWork session complete.\n")

    # 10. Prompt for review
    try:
        answer = input("\nRun review now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer in ("", "y", "yes"):
        try:
            return cmd_review(args)
        except NotImplementedError:
            print("  (tasks review is not yet implemented — run it manually)")

    return 0


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
    # 1. Resolve task
    task_rel = find_task(getattr(args, 'task', None))
    task_dir = TASKS_ROOT / task_rel

    # 2. Read frontmatter and update status in_progress → reviewing
    fm = read_frontmatter(task_dir / "CLAUDE.md")
    if fm.get("status") == "in_progress":
        fm["status"] = "reviewing"
        write_frontmatter(task_dir / "CLAUDE.md", fm)

    # 3. Determine N = next_iteration - 1 (review belongs to the same iteration as last work session)
    n = next_iteration(task_dir) - 1
    if n < 1:
        n = 1

    # 4. Create review log
    log_path = log_review(task_dir, n)

    # 5. Print header
    print(f"\n=== tasks review: {task_dir} (iteration {n}) ===\n")

    # 6. Find AI CLI
    cli = find_ai_cli()
    if cli is None:
        print("Error: No AI CLI found (tried: claude, codex, agy). Install one to run review sessions.")
        sys.exit(1)

    # 7. Run review session
    run_ai_review(task_dir)

    # 8. Prompt for outcome
    try:
        answer = input("\nReview passed? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer in ("y", ""):
        print("✓ Review passed.")
        update_context_log(task_dir, n)
        try:
            run_done = input("Run tasks done? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if run_done in ("", "y", "yes"):
            try:
                return cmd_done(args)
            except NotImplementedError:
                print("  (tasks done is not yet implemented — run it manually)")
    else:
        # Failed path
        try:
            failure_note = input("What failed? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            failure_note = ""
        # Append failure note to review log
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n---\nOutcome: failed\nFailure note: {failure_note}\n")
        print("Re-run tasks work when ready.")
        try:
            run_work = input("Run tasks work now? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if run_work in ("", "y", "yes"):
            try:
                return cmd_work(args)
            except NotImplementedError:
                print("  (tasks work is not yet implemented — run it manually)")

    return 0


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
    # 1. Resolve task (find_task returns path relative to TASKS_ROOT)
    task_rel = find_task(getattr(args, 'task', None))
    task_dir = TASKS_ROOT / task_rel

    # 2. Read frontmatter
    fm = read_frontmatter(task_dir / "CLAUDE.md")

    # 3. Get current iteration N (last completed iteration)
    n = max(next_iteration(task_dir) - 1, 1)

    # 4. Parse declared deliverables from task.md
    declared = detect_outputs(task_dir, n)

    # 5. Check which exist on disk; warn about missing
    for name in declared:
        if not (task_dir / name).exists():
            print(f"⚠ Missing: {name}")

    # 6. Confirm outputs with user
    approved = confirm_outputs(declared)

    # 7. Update frontmatter: set status = done, append confirmed outputs (no duplicates)
    fm["status"] = "done"
    existing_outputs = fm.setdefault("outputs", [])
    for o in approved:
        if o not in existing_outputs:
            existing_outputs.append(o)
    write_frontmatter(task_dir / "CLAUDE.md", fm)

    print(f"\n✓ Task marked done: {task_dir}\n")

    # 8. Run README rebuild (errors are caught — must not crash done flow)
    try:
        rebuild_readme()
    except Exception as exc:
        print(f"⚠ README rebuild error: {exc}")

    # 9. Offer to commit
    try:
        answer = input("Commit? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer in ("y", "yes"):
        git_stage_and_commit(task_dir)

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print a status table for all tasks, optionally filtered by session, type, or open status.

    Steps (SEC-11):
        1. list_tasks(filter_session=args.session, filter_type=args.type)
        2. Optionally filter out "done" tasks when args.open is True
        3. render_status_table(tasks)
    Returns 0 on success, non-zero on error.
    """
    session_filter = getattr(args, "session", None)
    type_filter = getattr(args, "type", None)
    open_only = getattr(args, "open", False)

    tasks = list_tasks(filter_session=session_filter, filter_type=type_filter)

    if open_only:
        # Filter out "done" tasks by reading each task's frontmatter
        tasks = [
            t for t in tasks
            if read_frontmatter(TASKS_ROOT / t / "CLAUDE.md").get("status") != "done"
        ]

    render_status_table(tasks)
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Transcribe audio files in a task's raw/audio/ dir using mlx_whisper (sequential).

    Steps (SEC-12):
        1. Resolve task via find_task(args.task)
        2. find_audio_files() — skip already-transcribed
        3. run_transcription() for each file sequentially
    Returns 0 on success, non-zero on error.
    """
    task_rel = find_task(getattr(args, 'task', None))
    task_dir = TASKS_ROOT / task_rel

    audio_files = find_audio_files(task_dir)
    if not audio_files:
        print(f"No audio files found in {task_dir}/raw/audio/")
        return 0

    for audio_file in audio_files:
        run_transcription(audio_file, task_dir)

    print(f"Transcribed {len(audio_files)} file(s).")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Open task.md in $EDITOR (fallback: open -t on macOS).

    Steps (SEC-12):
        1. Resolve task via find_task(args.task)
        2. Open task_dir/task.md in os.environ['EDITOR'] or subprocess 'open -t'
    Returns 0 on success, non-zero on error.
    """
    task_rel = find_task(getattr(args, 'task', None))
    task_dir = TASKS_ROOT / task_rel
    task_md = task_dir / "task.md"

    if not task_md.exists():
        print(f"Error: task.md not found at {task_md}")
        return 1

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        subprocess.run([editor, str(task_md)])
    else:
        subprocess.run(["open", "-t", str(task_md)])  # macOS TextEdit fallback

    return 0


# === DAEMON MANAGEMENT ===

_PLIST_LABEL = "com.tasks.audiowatcher"
_PLIST_DST = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"
_LOG_FILE = Path.home() / ".local" / "var" / "log" / "tasks-daemon.log"
_WATCH_SCRIPT = TASKS_ROOT / "scripts" / "watch-audio.sh"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>{watch_script}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_file}</string>
  <key>StandardErrorPath</key>
  <string>{log_file}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TASKS_ROOT</key>
    <string>{tasks_root}</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
"""


def _daemon_install() -> int:
    if not _WATCH_SCRIPT.exists():
        print(f"Error: watch script not found at {_WATCH_SCRIPT}")
        print("Expected scripts/watch-audio.sh in the tasks repo.")
        return 1

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_DST.parent.mkdir(parents=True, exist_ok=True)

    plist_content = _PLIST_TEMPLATE.format(
        label=_PLIST_LABEL,
        watch_script=str(_WATCH_SCRIPT),
        log_file=str(_LOG_FILE),
        tasks_root=str(TASKS_ROOT),
    )
    _PLIST_DST.write_text(plist_content)

    result = subprocess.run(
        ["launchctl", "load", "-w", str(_PLIST_DST)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error loading plist: {result.stderr.strip()}")
        return 1

    print(f"Installed: {_PLIST_DST}")
    print(f"Log:       {_LOG_FILE}")
    print("Daemon is running and will auto-start on login.")
    return 0


def _daemon_uninstall() -> int:
    if not _PLIST_DST.exists():
        print("Daemon is not installed.")
        return 0

    subprocess.run(
        ["launchctl", "unload", "-w", str(_PLIST_DST)],
        capture_output=True,
    )
    _PLIST_DST.unlink(missing_ok=True)
    print(f"Uninstalled: {_PLIST_DST}")
    return 0


def _daemon_status() -> int:
    result = subprocess.run(
        ["launchctl", "list", _PLIST_LABEL],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("stopped  (not loaded)")
        return 1

    # launchctl list output includes PID on first line when running
    lines = result.stdout.strip().splitlines()
    pid = None
    for line in lines:
        if '"PID"' in line or line.startswith("{"):
            continue
        parts = line.split()
        if parts and parts[0].isdigit():
            pid = parts[0]
            break

    # Simpler: parse JSON-style output for PID key
    import re as _re
    m = _re.search(r'"PID"\s*=\s*(\d+)', result.stdout)
    if m:
        pid = m.group(1)
        print(f"running  (PID {pid})")
    else:
        print("loaded but not running  (check log for errors)")
    return 0


def _daemon_log() -> int:
    if not _LOG_FILE.exists():
        print(f"No log file at {_LOG_FILE} — has the daemon been installed?")
        return 1
    try:
        subprocess.run(["tail", "-f", str(_LOG_FILE)])
    except KeyboardInterrupt:
        pass
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Manage the audio-watcher daemon (install/uninstall/status/log)."""
    sub = getattr(args, "daemon_command", None)
    if sub == "install":
        return _daemon_install()
    if sub == "uninstall":
        return _daemon_uninstall()
    if sub == "status":
        return _daemon_status()
    if sub == "log":
        return _daemon_log()
    print("Usage: tasks daemon <install|uninstall|status|log>")
    return 1


# === ARGUMENT PARSER ===


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level ArgumentParser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="tasks",
        description="Local task lifecycle orchestrator",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # tasks new
    new = subparsers.add_parser("new", help="Create a new task interactively")
    new.add_argument("--session", metavar="DDMMYYYY", help="Override session folder (default: today)")
    new.add_argument("--type", dest="type", choices=TASK_TYPES, help="Pre-select task type")

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

    # tasks daemon <sub>
    daemon = subparsers.add_parser("daemon", help="Manage the audio-watcher daemon")
    daemon_sub = daemon.add_subparsers(dest="daemon_command", metavar="SUBCOMMAND")
    daemon_sub.add_parser("install", help="Install and start the daemon (auto-starts on login)")
    daemon_sub.add_parser("uninstall", help="Stop and remove the daemon")
    daemon_sub.add_parser("status", help="Show daemon running/stopped status")
    daemon_sub.add_parser("log", help="Tail the daemon log file")

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
        "daemon": cmd_daemon,
    }

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = dispatch.get(args.command)
    if handler is None:
        parser.error(f"Unknown command: {args.command!r}")

    try:
        sys.exit(handler(args))  # type: ignore[call-arg]
    except NotImplementedError:
        print(f"Command '{args.command}' is not yet implemented.")
        sys.exit(1)


if __name__ == "__main__":
    main()
