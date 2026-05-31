# ARCHITECTURE.md — Tasks CLI: Local Executor

This document is the primary reference for developers implementing `scripts/tasks.py`.
It describes module layout, data flow, schema, error strategy, and key algorithms.
All function stubs are in `scripts/tasks.py`; this document explains *why* they exist
and *how* they should be implemented.

---

## 1. Repository Layout

```
task_cli/
├── ARCHITECTURE.md          ← this file
├── pyproject.toml           ← uv-compatible; ruamel.yaml dep
├── .gitignore
├── scripts/
│   ├── tasks.py             ← single-file CLI (entry point, all logic)
│   └── rebuild_readme.py    ← standalone README regenerator
└── tests/
    └── test_tasks.py        ← SEC-13 edge case stubs
```

`tasks.py` is intentionally a single file to keep installation trivial:
```bash
ln -sf $(pwd)/scripts/tasks.py ~/.local/bin/tasks
chmod +x ~/.local/bin/tasks
```

---

## 2. Module Layout Inside `tasks.py`

Sections are delimited by `# === SECTION NAME ===` headers:

| Section | Contents |
|---------|----------|
| IMPORTS | stdlib only + deferred ruamel.yaml import |
| CONSTANTS | `TASKS_ROOT`, `AI_CASCADE`, `TASK_TYPES`, `STOPWORDS`, `FRONTMATTER_KEYS_ORDER`, `STATUS_ICONS`, `CLAUDE_MD_TEMPLATE` |
| FRONTMATTER I/O | `read_frontmatter`, `write_frontmatter`, `_split_frontmatter` |
| TASK RESOLUTION | `list_tasks`, `pick_task`, `find_task`, `_fzf_available`, `_numbered_list_pick` |
| SLUG & TYPE HELPERS | `heuristic_slug`, `pick_task_type`, `confirm_slug` |
| AI CASCADE | `find_ai_cli`, `run_ai_gen`, `run_ai_work`, `run_ai_review`, `_build_review_prompt` |
| ITERATION & VERSIONING | `next_iteration`, `versioned_deliverable`, `log_work`, `log_review`, `update_context_log` |
| OUTPUT DETECTION & README | `detect_outputs`, `confirm_outputs`, `rebuild_readme` |
| STATUS TABLE | `render_status_table` |
| TRANSCRIPTION HELPERS | `find_audio_files`, `run_transcription` |
| GIT HELPERS | `git_stage_and_commit` |
| COMMAND IMPLEMENTATIONS | `cmd_new`, `cmd_work`, `cmd_review`, `cmd_done`, `cmd_status`, `cmd_transcribe`, `cmd_edit` |
| ARGUMENT PARSER | `build_parser` |
| ENTRY POINT | `main` |

---

## 3. CLAUDE.md Frontmatter Schema

Every task has a `CLAUDE.md` at `TASKS_ROOT/DDMMYYYY/slug/CLAUDE.md`.
The file starts with a YAML frontmatter block delimited by `---`.

### Schema

```yaml
---
slug: e300-horynich-summary        # kebab-case, ASCII, 3-5 words
type: reporting                    # one of TASK_TYPES
status: todo                       # todo | in_progress | reviewing | done
created: "2026-05-31T14:22:00Z"   # ISO-8601 UTC string
session: "31052026"                # DDMMYYYY folder name
deliverables: []                   # list of declared output filenames (no path)
outputs: []                        # list of confirmed output paths (relative to TASKS_ROOT)
---
```

### Status Transitions

```
todo → in_progress   (cmd_work)
in_progress → reviewing   (cmd_review)
reviewing → done   (cmd_done)
in_progress → done   (cmd_done quick path, skipping review)
```

### Key Ordering

`write_frontmatter` must preserve the order defined in `FRONTMATTER_KEYS_ORDER`.
`ruamel.yaml` with `typ='rt'` (round-trip) preserves insertion order and inline comments.

### Body Text

Everything after the closing `---` is Markdown body. `write_frontmatter` must
preserve the body byte-for-byte. `_split_frontmatter` handles the split.

---

## 4. Data Flow per Command

### `tasks new` (SEC-7)

```
stdin (multi-line)
    → raw/context.md (saved as-is)
    → run_ai_gen(prompt=context, task_dir=tmp)   [non-interactive, captures stdout]
    → task.md (AI output)
    → heuristic_slug(context)
    → confirm_slug(suggested)          [user: Enter / edit / 'ai']
    → pick_task_type()                 [numbered list]
    → mkdir DDMMYYYY/slug/{raw/audio,raw/files,transcriptions,iterations}/
    → write CLAUDE.md (CLAUDE_MD_TEMPLATE rendered)
    → write raw/context.md
    → write task.md
    → prompt "tasks work <session/slug>? [Y/n]"
```

### `tasks work` (SEC-8)

```
find_task(args.task)
    → write_frontmatter(status: in_progress)
    → N = next_iteration(task_dir)
    → versioned_deliverable(name, N) for each deliverable
    → log stub = log_work(task_dir, N, ai_cli, exit_code=None)
    → run_ai_work(task_dir)   [inherits terminal, cwd=task_dir]
    → log_work appends summary (exit code, timestamp)
    → prompt "Run review now? [Y/n]"  → cmd_review if yes
```

### `tasks review` (SEC-9)

**Iteration N for review:** After `cmd_work` runs, `next_iteration()` returns `work_N + 1`.
Review belongs to the *same* iteration as the work it reviews, so:
```python
N = next_iteration(task_dir) - 1
```
This pairs `N_work_<ts>.md` with `N_review_<ts>.md`. Do NOT call `next_iteration()` naively
here — that would create a mismatched `(N+1)_review_<ts>.md` log.

```
find_task(args.task)
    → write_frontmatter(status: reviewing)
    → N = next_iteration(task_dir) - 1   ← same N as the preceding work session
    → log stub = log_review(task_dir, N, passed=None)
    → _build_review_prompt(task_dir, N)
    → run_ai_review(task_dir)   [inherits terminal]
    → prompt "Review passed? [y/n]"
        y: update_context_log(task_dir, N, summary)
           prompt "tasks done? [Y/n]"  → cmd_done if yes
        n: "What failed?" → stdin
           log_review appends failure notes
           prompt "tasks work? [Y/n]"  → cmd_work if yes (which increments N to N+1)
```

### `tasks done` (SEC-10)

```
find_task(args.task)
    → write_frontmatter(status: done)
    → N = next_iteration(task_dir) - 1   (current iteration)
    → detect_outputs(task_dir, N)
    → confirm_outputs(found, missing)
    → write_frontmatter(outputs: [...])
    → rebuild_readme()
    → prompt "Commit? [y/N]"  → git_stage_and_commit if yes
```

### `tasks status` (SEC-11)

```
list_tasks(filter_session, filter_type)
    → read_frontmatter() for each
    → render_status_table(tasks, filter_open)
```

### `tasks transcribe` (SEC-12)

```
find_task(args.task)
    → find_audio_files(task_dir)   [skips already-transcribed]
    → for each: run_transcription(audio_file, task_dir)   [sequential]
```

### `tasks edit` (SEC-12)

```
find_task(args.task)
    → open task_dir/task.md in $EDITOR or 'open -t' (macOS fallback)
```

---

## 5. How Iteration N is Determined

`next_iteration(task_dir)` scans `task_dir/iterations/` for files matching:
```
<N>_work_<timestamp>.md
<N>_review_<timestamp>.md
```

The regex `r'^(\d+)_(?:work|review)_'` extracts the leading integer N from each filename.
`next_iteration` returns `max(found_Ns) + 1`, or `1` if the directory is empty.

**Important:** gaps in numbering are treated as valid history. If iterations 1, 3 exist,
the next is 4 — not 2. This prevents overwriting logs after a manual rollback.

---

## 6. Output Versioning

`versioned_deliverable(name, n)` uses `re.sub`:

```python
re.sub(r'_v\d+', f'_v{n}', name)
```

If the name contains no `_vN` suffix, the function appends `_v{n}` before the extension:

```python
# e.g. "slides_compressed.md" at iteration 2 → "slides_compressed_v2.md"
# e.g. "slides_compressed_v1.md" at iteration 2 → "slides_compressed_v2.md"
```

Declared deliverables come from `## Deliverables` in `task.md`, parsed line by line
for Markdown list items (`- filename`). The declared name is used as the pattern;
`detect_outputs` checks for the versioned filename in `task_dir`.

---

## 7. ruamel.yaml Round-Trip Strategy

`read_frontmatter` and `write_frontmatter` use `ruamel.yaml.YAML(typ='rt')`.
This preserves:
- Key order (via `CommentedMap`)
- Inline YAML comments (`# ...`)
- Scalar styles (block vs. flow)

**Implementation contract for `write_frontmatter`:**

1. Read the full file text.
2. `_split_frontmatter(text)` → `(yaml_block, body_text)`.
3. Parse `yaml_block` with `ruamel.yaml.YAML(typ='rt').load(...)`.
4. Mutate the resulting `CommentedMap` in-place (preserve key order via `FRONTMATTER_KEYS_ORDER`).
5. Serialize back to a string with `ruamel.yaml.YAML(typ='rt').dump(...)`.
6. Reconstruct: `---\n{yaml}\n---\n{body_text}`.
7. Write atomically (write to `.tmp`, then `os.replace`).

**`_split_frontmatter` algorithm:**
- If text starts with `---\n`, find the second `---` line.
- Return `(content_between_delimiters, everything_after_second_delimiter)`.
- If no valid frontmatter found, return `('', text)`.

---

## 8. AI Cascade

`find_ai_cli()` iterates `AI_CASCADE = ["claude", "codex", "agy"]` and returns the
first name for which `shutil.which(name)` is not None.

| Function | Mode | Process | stdin/stdout |
|----------|------|---------|--------------|
| `run_ai_gen` | non-interactive | `subprocess.run(capture_output=True)` | prompt via stdin or `--message` flag |
| `run_ai_work` | yolo/autonomous | `subprocess.run(cwd=task_dir)` | inherits terminal |
| `run_ai_review` | yolo/autonomous | `subprocess.run(cwd=task_dir)` | inherits terminal |

`run_ai_gen` is used only during `cmd_new` to generate `task.md` from context.
The exact CLI flags for `claude`, `codex`, and `agy` differ; the implementation must
handle each tool's interface (e.g., `claude --print <prompt>`, `codex <prompt>`).

When no AI CLI is found, commands that require generation (`cmd_new`) must print
a user-visible error and exit non-zero. Commands that only launch a session
(`cmd_work`, `cmd_review`) should also error clearly.

---

## 9. Task Resolution (`find_task`)

`find_task(arg)` resolves a task directory from an optional string argument:

1. **Exact path**: if `arg` is a valid directory containing `CLAUDE.md`, use it.
2. **session/slug format**: if `arg` matches `DDMMYYYY/slug` and the directory exists, use it.
3. **Slug only**: if `arg` matches a unique slug across all sessions, use it.
4. **Picker**: if `arg` is None or ambiguous, call `pick_task(list_tasks())`.

`pick_task` prefers `fzf` (piped list of `session/slug` strings).
If `fzf` is absent (`_fzf_available()` returns False), falls back to `_numbered_list_pick`.

---

## 10. Slug Generation

`heuristic_slug(text)` pipeline:
1. Lowercase the input.
2. Remove all non-alphanumeric, non-space characters (Unicode-safe via `re.sub`).
3. Split into tokens.
4. Filter out tokens in `STOPWORDS`.
5. Take first 3–4 remaining tokens.
6. Join with `-`.

`confirm_slug(suggested)` shows:
```
Suggested slug: e300-horynich-summary  [Enter=confirm / type new slug / 'ai'=regenerate]
```
- Empty input → accept `suggested`.
- `'ai'` input → call `run_ai_gen` with a slug-specific prompt → parse output → loop.
- Any other input → use as the new slug (validate: lowercase, kebab-case, no spaces).

---

## 11. Error Handling Strategy

| Situation | Behavior |
|-----------|----------|
| No AI CLI available | Print human-readable error + hint to install; exit 1 |
| fzf absent | Silently fall back to numbered list (not an error) |
| Corrupt / missing frontmatter | `read_frontmatter` returns `{}`; caller decides |
| Task directory not found | Print error with path; exit 1 |
| Missing declared deliverable | Warn (stderr), continue; do not exit |
| `mlx_whisper` not installed | Print install hint (`pip install mlx-whisper`); exit 1 |
| `ruamel.yaml` not installed | Print install hint (`pip install ruamel.yaml`); exit 1 |
| Subprocess non-zero exit | Log exit code in iteration log; propagate to caller |
| Atomic write failure | Leave `.tmp` file; do not corrupt original |

All user-facing errors go to stderr. All prompts/confirmations go to stdout.
Exceptions are caught at the command level (`cmd_*`) and converted to exit codes.

---

## 12. Iteration Log File Format

`iterations/<N>_work_<ts>.md` (created by `log_work`):

```markdown
# Work Iteration N — <ISO timestamp>

**AI CLI:** claude
**Task:** DDMMYYYY/slug

## Session Notes
<!-- Populated by AI or manually after session -->

## Exit
- Exit code: 0
- Completed at: <ISO timestamp>
```

`iterations/<N>_review_<ts>.md` (created by `log_review`):

```markdown
# Review Iteration N — <ISO timestamp>

**Task:** DDMMYYYY/slug

## Review Result
- Passed: yes/no

## Failure Notes
<!-- Populated if passed=no -->
```

Timestamp format: `YYYYMMDD_HHMMSS` in the filename, ISO-8601 in the body.

---

## 13. `rebuild_readme.py` Design

Called by `tasks done` step 6 as a subprocess:
```python
subprocess.run([sys.executable, str(TASKS_ROOT / "scripts" / "rebuild_readme.py")])
```

It reads `TASKS_ROOT` from its own `__file__` path (same resolution as `tasks.py`).
The three sections it manages are delimited by HTML comments in README.md:
```
<!-- tasks-overview-start --> ... <!-- tasks-overview-end -->
<!-- sessions-start --> ... <!-- sessions-end -->
<!-- archive-start --> ... <!-- archive-end -->
```
`inject_sections` finds these markers and replaces the content between them.
If markers are absent, sections are appended before the `<!-- last-updated -->` marker.

---

## 14. Testing Strategy (SEC-13)

Tests are in `tests/test_tasks.py`. Each test maps to one SEC-13 edge case:

| Test | What to mock/setup | Key assertion |
|------|--------------------|---------------|
| `test_no_ai_cli_available` | `shutil.which` returns None | `find_ai_cli()` returns None; cmd errors cleanly |
| `test_fzf_absent_falls_back_to_numbered_list` | `shutil.which('fzf')` = None; stdin = '1' | `pick_task()` returns first task |
| `test_corrupt_frontmatter_does_not_crash` | Broken YAML in tmp CLAUDE.md | `read_frontmatter()` returns `{}` |
| `test_missing_claude_md_returns_empty_dict` | Non-existent path | `read_frontmatter()` returns `{}` |
| `test_next_iteration_after_rollback` | iterations/1_work_..., iterations/3_work_... | returns 4 |
| `test_done_with_no_deliverables_does_not_crash` | Empty Deliverables section | `detect_outputs()` returns `[]` |
| `test_done_warns_on_missing_declared_file` | Declared but absent file | warning on stderr, no exception |
| `test_list_tasks_returns_all_tasks_in_session` | Two sessions in tmp TASKS_ROOT | filter returns exactly 2 |
| `test_write_frontmatter_preserves_body_and_comments` | CLAUDE.md with inline comments + body | body and comments unchanged |

Use `pytest` with `tmp_path` fixtures. Mock filesystem interactions with `monkeypatch`.
Do not test against the real `TASKS_ROOT` or call real AI CLIs in unit tests.
