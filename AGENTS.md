# Agent Instructions

A local Streamlit app for Windows that turns YouTube transcripts into copy-and-paste ChatGPT prompts. It makes no AI API calls; keep it that way unless the owner decides otherwise.

## Single-Video Analysis

Single-video analysis must stay usable and independently releasable throughout playlist development. Playlist work must not break it, must not make it depend on playlist-only code or packages (for example, a top-level `yt_dlp` import in `app.py`), and must leave `main` releasable with single-video mode alone after every merge.

## Branches

- `main` is the canonical branch. Start every branch from `main` and open every pull request against it.
- `master` and tag `v1.0.0-mvp1` hold the pre-upload history, which shares no commits with `main`. Do not push to, merge, rebase, or delete them. Never use `--allow-unrelated-histories`.
- Do not delete or rewrite other branches, including `claude/affectionate-pasteur-n4mvfg` (Chrome extension).
- Keep each pull request to one concern.
- Never commit Git internals (`HEAD`, `config`, `index`, `*.sample`), `__pycache__/`, `*.pyc`, `.venv/`, or a nested copy of the project. CI rejects tracked `__pycache__/`, `*.pyc`, hook `*.sample` files, and root-level Git files such as `HEAD`, `config` and `index`.

## Tests

Run before every push. CI runs the same checks on `windows-latest` with Python 3.14.

```powershell
.\.venv\Scripts\python.exe -m py_compile .\app.py .\tests_manual.py
.\.venv\Scripts\python.exe .\tests_manual.py
```

On macOS or Linux, run `python -m py_compile app.py tests_manual.py` and `python tests_manual.py`. The last line must be `All manual regression checks passed.` When you add a Python module, add it to the `py_compile` step here and in `.github/workflows/ci.yml`.

## Roles

- **Owner (Pary):** sets priorities, decides scope, and authorizes every merge.
- **Builder (Claude Code):** the only agent that edits files, commits, or pushes. Works on a feature branch, opens a draft pull request, runs the tests before each push, and answers every review finding with a fix commit or a stated reason.
- **Reviewer (Codex):** read-only. Reviews the pull request diff at a named head commit and posts findings as PR comments. Does not edit, commit, or push.
- One builder per branch at a time. The owner may reassign roles for a pull request.

## Merging

No agent merges a pull request, pushes to `main`, or enables auto-merge without explicit authorization from the owner for that specific pull request. An approving review or green CI is not authorization.
