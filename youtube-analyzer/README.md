# YouTube Video Analyzer

A local Python Streamlit app that fetches YouTube transcripts and prepares copy-and-paste ChatGPT analysis prompts.

## What The App Does

- Accepts a YouTube URL or video ID.
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
- Includes a small debug info expander.

## Current Limitations

- Only videos with available English transcripts work.
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
