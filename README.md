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
  - Generates a final whole-playlist synthesis prompt.
  - Records failed/skipped videos instead of silently omitting them.
  - Exports a ZIP package with transcripts, prompts, manifest, and failure evidence.
- Includes a small debug info expander.

## Whole-Playlist Workflow

In the app, choose **Whole playlist**, paste a playlist URL, select the analysis mode, and click **Analyze Whole Playlist**.

For large playlists, the app deliberately uses a two-stage manual workflow:

1. Analyze each generated playlist batch in ChatGPT.
2. Paste the completed batch analyses into the generated final synthesis prompt.

This avoids trying to place hundreds of videos into one prompt while preserving which ideas came from which video.

The app still does **not** automatically send transcripts to an AI service.

## Current Limitations

- Only videos with available English transcripts are currently analyzed.
- Playlist extraction depends on YouTube remaining accessible to `yt-dlp`; YouTube changes can occasionally require a dependency update.
- Very large playlists can take several minutes to collect and may encounter YouTube transcript rate limits. Failures are recorded in the playlist manifest.
- Some videos may block or disable transcripts.
- No AI summarization is performed inside this app.
- No OpenAI API calls are used.
- No browser automation is used.
- The user manually copies or downloads prompts and pastes them into ChatGPT.

## Setup On Windows PowerShell

Open PowerShell and go to the project folder:

```powershell
cd C:\p\youtube-analyzer
```

Activate the existing virtual environment:

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

## Dependencies

Runtime dependencies are listed in `requirements.txt`.

Current pinned versions:

- `streamlit==1.56.0`
- `youtube-transcript-api==1.2.4`
- `yt-dlp>=2025.1.26,<2027`
