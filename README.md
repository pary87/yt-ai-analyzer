# YouTube Video Analyzer

A local Python Streamlit app for analyzing YouTube videos.

## Project Type

This project is a Python Streamlit app.

It is not a Node, React, or Vite app.

## Current Feature List

- Streamlit app
- YouTube URL input
- Video ID extraction
- Transcript fetching
- Cleaned transcript display
- Transcript metadata
- `transcript.txt` download
- Debug info expander

## Current MVP Status

MVP-1.5: Transcript extraction and cleanup complete.

## How to Run

```powershell
cd C:\p\youtube-analyzer
.\.venv\Scripts\Activate.ps1
streamlit run .\app.py
```

If PowerShell says scripts are disabled, run this first in the same terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Open the app in your browser:

```text
http://localhost:8501
```

## Setup

Install the required Python packages:

```powershell
pip install -r requirements.txt
```

## Known Limitations

- Only videos with available English transcripts work.
- Some videos may block or disable transcripts.
- No AI summarization yet.
- No OpenAI API integration yet.

## Important

Do not run this app with:

```powershell
python .\app.py
```

Streamlit apps must be launched with `streamlit run`.
