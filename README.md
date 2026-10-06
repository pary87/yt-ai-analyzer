# YouTube Video Analyzer

A local Python Streamlit app that fetches YouTube transcripts and prepares copy-and-paste ChatGPT analysis prompts.

## What The App Does

- Accepts a YouTube video URL/video ID or a full YouTube playlist URL/playlist ID.
- Extracts the YouTube video ID from common URL formats.
- Fetches an available English transcript.
- Cleans the transcript into more readable text.
- Displays transcript metadata, including character count, word count, and estimated reading time.
- Shows a transcript preview and full transcript expander.
- Downloads the cleaned transcript as a `.txt` file.
- Generates a ChatGPT analysis prompt for manual copy/paste.
- Supports prompt modes:
  - General Analysis
  - Study Notes
  - Technical / Engineering Review
  - Action Plan
- Creates chunked ChatGPT prompts for very long transcripts.
- Adds whole-playlist analysis:
  - Discovers every playable video in a playlist.
  - Attempts to collect an English transcript for each video.
  - Preserves playlist order and video attribution.
  - Splits large playlists into ChatGPT-sized analysis batches.
  - Combines batch results through group prompts and a final whole-playlist synthesis prompt.
  - Stops collecting when YouTube blocks requests, and keeps collected transcripts while the app runs so a later run fetches only the missing videos.
  - Records failed/skipped videos instead of silently omitting them.
  - Exports a ZIP package with transcripts, prompts, manifest, and failure evidence.
- Includes a small debug info expander.

## Whole-Playlist Workflow

In the app, choose **Whole playlist**, paste a playlist URL, select the analysis mode, and click **Analyze Whole Playlist**. After collecting transcripts, the app shows how many ChatGPT rounds the playlist needs.

So that no single prompt grows too large, the manual workflow is staged:

1. Paste each batch prompt into a new ChatGPT chat and keep the "Batch synthesis" section of each answer (at most 250 words).
2. If there are more than 10 batches, paste those sections into the group prompts (up to 10 batches each) and keep each "Group synthesis" section (at most 400 words).
3. Paste the synthesis sections into the final whole-playlist prompt, which also lists the videos that have no transcript.

Each step preserves which ideas came from which video. Changing the prompt mode rebuilds every prompt from the collected transcripts without downloading them again.

The app waits one second between transcript downloads. If YouTube starts blocking requests, collection stops, the transcripts already collected are kept while the app is running, and the remaining videos are marked "not attempted". Click **Analyze Whole Playlist** again later to fetch only the missing videos.

The app still does **not** automatically send transcripts to an AI service.

## Current Limitations

- Only videos with available English transcripts are currently analyzed.
- Playlist extraction depends on YouTube remaining accessible to `yt-dlp`; YouTube changes can occasionally require a dependency update.
- Very large playlists take several minutes to collect (at least three minutes for 180 videos) and may hit YouTube transcript rate limits. Failures are recorded in the playlist manifest.
- Some videos may block or disable transcripts.
- No AI summarization is performed inside this app.
- No OpenAI API calls are used.
- No browser automation is used.
- The user manually copies or downloads prompts and pastes them into ChatGPT.

## Setup On Windows PowerShell

Use Python 3.14, the version CI tests.

First time only, clone the repository and create a Python 3.14 virtual environment inside it:

```powershell
git clone https://github.com/pary87/yt-ai-analyzer.git
cd yt-ai-analyzer
py -3.14 -m venv .venv
```

Already set up? Open PowerShell in your existing project folder instead. If it still tracks `master`, follow [Migrating An Existing `master` Installation](#migrating-an-existing-master-installation) first.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell says scripts are disabled, run this first in the same terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Run The Streamlit App

After activating the virtual environment, run:

```powershell
streamlit run .\app.py
```

Open the app in your browser:

```text
http://localhost:8501
```

Do not run this app with:

```powershell
python .\app.py
```

Streamlit apps must be launched with `streamlit run`.

Or double-click `Run YouTube Analyzer.bat`. It runs the app from the folder the launcher is in, using that folder's `.venv`, and prints the setup commands if `.venv` is missing. To start it from the desktop, create a shortcut to it rather than copying the file.

## Run Manual Regression Checks

After activating the virtual environment, run:

```powershell
.\.venv\Scripts\python.exe -m py_compile .\app.py
.\.venv\Scripts\python.exe -m py_compile .\playlist_analysis.py
.\.venv\Scripts\python.exe -m py_compile .\tests_manual.py
.\.venv\Scripts\python.exe .\tests_manual.py
```

Expected success message:

```text
All manual regression checks passed.
```

GitHub Actions runs the same checks on Windows for every pull request and every push to `main`.

## Branches

`main` is the canonical branch. `master` and tag `v1.0.0-mvp1` keep the original local history; they are preserved but no longer updated. Rules for AI agents working in this repository are in [AGENTS.md](AGENTS.md).

## Migrating An Existing `master` Installation

Older copies of this project track the `master` branch. `main` and `master` share no history, so `git pull` on `master` will never receive new work. Switching adds whole-playlist mode; step 5 installs its `yt-dlp` dependency. Single-video analysis works as before, and its button is now labelled **Analyze Video**. A fresh clone already uses `main`.

Run these in PowerShell from the existing project folder, for example `C:\p\youtube-analyzer`:

1. Check for work that exists only on this computer:

   ```powershell
   git fetch origin
   git status --short
   git log --oneline origin/master..master
   ```

   Both commands after `git fetch` should print nothing.

   - If `git status` lists files, set them aside with `git stash push --include-untracked -m before-main`, then run the commands again. To get them back later, run `git switch master` and `git stash pop`.
   - If `git log` lists commits, they are not on GitHub. Publish them on a new branch without changing `master`, using `git push origin master:refs/heads/backup/master-local`, then stop and ask the builder to port them to `main` in a separate pull request. Do not run a plain `git push` on `master`.

2. Keep a bookmark of the current state:

   ```powershell
   git branch backup/master-local master
   ```

3. Switch to `main`:

   ```powershell
   git switch --track origin/main
   ```

   If a local `main` already exists, run `git switch main` and then `git pull --ff-only` instead. If Git refuses because local changes or untracked files would be overwritten, go back to step 1. Your `.venv` folder is not affected.

4. Check that the existing `.venv` uses Python 3.14:

   ```powershell
   .\.venv\Scripts\python.exe --version
   ```

   If it prints another version, first confirm `py -3.14 --version` works (install Python 3.14 if it does not). Then keep the old environment as a fallback and create a new one:

   ```powershell
   Rename-Item .venv .venv-old
   py -3.14 -m venv .venv
   ```

   Delete `.venv-old` once step 5 passes.

5. Update dependencies and run the checks:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m py_compile .\app.py .\playlist_analysis.py .\tests_manual.py
   .\.venv\Scripts\python.exe .\tests_manual.py
   ```

From now on, use `git pull` on `main`. To return to the old state, run `git switch master`. Do not merge `master` and `main` into each other.

If you copied the old `Run YouTube Analyzer.bat` somewhere else, such as the desktop, that copy still points at `C:\p\youtube-analyzer` and keeps working. Replace it with a shortcut to the launcher inside the project folder; a copy of the new launcher would look for the app next to itself.

## Dependencies

Runtime dependencies are listed in `requirements.txt`.

Current pinned versions:

- `streamlit==1.56.0`
- `youtube-transcript-api==1.2.4`
- `yt-dlp>=2026.8.19` (a minimum rather than a pin: YouTube changes regularly need newer `yt-dlp` releases)
