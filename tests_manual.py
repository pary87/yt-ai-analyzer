# This is a lightweight regression script, not a full production test suite.

import csv
import io
import subprocess
import sys
import zipfile
from pathlib import Path

from requests.exceptions import ConnectionError as RequestsConnectionError
from streamlit.testing.v1 import AppTest
from youtube_transcript_api import IpBlocked, TranscriptsDisabled

from playlist_analysis import (
    BATCH_SYNTHESIS_WORD_LIMIT,
    NOT_ATTEMPTED_MESSAGE,
    build_playlist_batch_prompt,
    build_playlist_group_prompt,
    build_playlist_manifest_csv,
    build_playlist_outputs,
    build_playlist_synthesis_prompt,
    build_playlist_units,
    collect_playlist_transcripts,
    describe_batch,
    extract_playlist_id,
    normalize_playlist_url,
    plan_synthesis_groups,
    split_playlist_units_into_batches,
    split_transcript_into_parts,
)

from app import (
    CHUNK_WORD_LIMIT,
    build_analysis_instructions,
    build_chunked_chatgpt_prompt,
    build_chatgpt_analysis_prompt,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    clean_transcript_text,
    extract_video_id,
    format_timestamp,
    get_transcript_error_message,
    slugify_prompt_mode,
    split_transcript_into_chunks,
)

PROJECT_DIR = Path(__file__).resolve().parent


def test_extract_video_id():
    expected_video_id = "dQw4w9WgXcQ"

    valid_inputs = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ]

    for video_input in valid_inputs:
        assert extract_video_id(video_input) == expected_video_id

    invalid_inputs = [
        "hello",
        "https://evilyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=bad",
    ]

    for video_input in invalid_inputs:
        assert extract_video_id(video_input) is None


def test_slugify_prompt_mode():
    assert slugify_prompt_mode("General Analysis") == "general_analysis"
    assert slugify_prompt_mode("Study Notes") == "study_notes"
    assert slugify_prompt_mode("Technical / Engineering Review") == "technical_engineering_review"
    assert slugify_prompt_mode("Action Plan") == "action_plan"


def test_calculate_transcript_metadata():
    transcript_text = "One two three."
    metadata = calculate_transcript_metadata(transcript_text)

    assert metadata["character_count"] == len(transcript_text)
    assert metadata["word_count"] == 3
    assert metadata["reading_time"] >= 1


def test_split_transcript_into_chunks():
    words = ["word"] * (CHUNK_WORD_LIMIT + 25)
    transcript_text = " ".join(words)
    chunks = split_transcript_into_chunks(transcript_text)

    assert len(chunks) > 1

    chunk_word_counts = []

    for chunk in chunks:
        chunk_word_count = len(chunk.split())
        chunk_word_counts.append(chunk_word_count)
        assert chunk_word_count <= CHUNK_WORD_LIMIT

    assert sum(chunk_word_counts) == len(words)


def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65.2) == "01:05"
    assert format_timestamp(3723) == "01:02:03"


def test_build_timestamped_transcript():
    segments = [
        {"start": 0, "text": "First transcript line."},
        {"start": 4.2, "text": "Next transcript line."},
    ]
    timestamped_transcript = build_timestamped_transcript(segments)

    assert "[00:00] First transcript line." in timestamped_transcript
    assert "[00:04] Next transcript line." in timestamped_transcript


def test_build_chatgpt_analysis_prompt_includes_title():
    metadata = {
        "character_count": 100,
        "word_count": 20,
        "reading_time": 1,
    }
    prompt = build_chatgpt_analysis_prompt(
        "dQw4w9WgXcQ",
        metadata,
        "Readable transcript text.",
        "General Analysis",
        video_title="Example Video Title",
    )

    assert "Video title: Example Video Title" in prompt


def test_build_chunked_chatgpt_prompt():
    full_metadata = {
        "character_count": 1000,
        "word_count": 200,
        "reading_time": 1,
    }
    chunk_text = "This is the chunk text."
    prompt_mode = "Study Notes"
    prompt = build_chunked_chatgpt_prompt(
        "dQw4w9WgXcQ",
        full_metadata,
        chunk_text,
        1,
        3,
        prompt_mode,
        video_title="Example Video Title",
    )

    assert "Video title: Example Video Title" in prompt
    assert "Whole transcript metadata" in prompt
    assert "Current chunk metadata" in prompt
    assert "Chunk: 1 of 3" in prompt
    assert build_analysis_instructions(prompt_mode) in prompt
    assert chunk_text in prompt



def test_extract_playlist_id():
    playlist_id = "PLR2bLIYLsk_SKlWWfw1A-vS7WzPswHb3c"

    valid_inputs = [
        f"https://www.youtube.com/playlist?list={playlist_id}",
        f"https://www.youtube.com/watch?v=dQw4w9WgXcQ&list={playlist_id}",
        playlist_id,
    ]

    for playlist_input in valid_inputs:
        assert extract_playlist_id(playlist_input) == playlist_id

    invalid_inputs = [
        "",
        "hello",
        "https://evilyoutube.com/playlist?list=PLR2bLIYLsk_SKlWWfw1A-vS7WzPswHb3c",
        "dQw4w9WgXcQ",
    ]

    for playlist_input in invalid_inputs:
        assert extract_playlist_id(playlist_input) is None

    assert normalize_playlist_url(playlist_id) == (
        f"https://www.youtube.com/playlist?list={playlist_id}"
    )


def test_playlist_batching_preserves_video_attribution():
    videos = [
        {
            "position": 1,
            "video_id": "aaaaaaaaaaa",
            "title": "First Video",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "transcript_text": " ".join(["one"] * 7),
            "metadata": {"word_count": 7},
        },
        {
            "position": 2,
            "video_id": "bbbbbbbbbbb",
            "title": "Second Video",
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "transcript_text": " ".join(["two"] * 7),
            "metadata": {"word_count": 7},
        },
    ]

    units = build_playlist_units(videos, word_limit=5)
    assert len(units) == 4
    assert units[0]["position"] == 1
    assert units[0]["part_number"] == 1
    assert units[1]["part_number"] == 2
    assert units[2]["position"] == 2

    batches = split_playlist_units_into_batches(units, word_limit=10)
    assert len(batches) >= 2
    assert sum(unit["word_count"] for batch in batches for unit in batch) == 14


def test_playlist_synthesis_prompt_mentions_missing_evidence():
    playlist_info = {
        "playlist_title": "Example Playlist",
        "playlist_id": "PL123456789012",
    }
    prompt = build_playlist_synthesis_prompt(
        playlist_info,
        "Study Notes",
        successful_video_count=8,
        total_video_count=10,
        total_batches=3,
        failure_count=2,
    )

    assert "Example Playlist" in prompt
    assert "Videos skipped or failed: 2" in prompt
    assert '[PASTE THE "Batch synthesis" SECTION FROM BATCH 3 HERE]' in prompt
    assert "Do not claim to have analyzed videos that were skipped or failed." in prompt


def _video(position, video_id, words=5):
    transcript_text = " ".join(["word"] * words)

    return {
        "position": position,
        "video_id": video_id,
        "title": f"Video {position}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "transcript_text": transcript_text,
        "timestamped_transcript": f"[00:00] {transcript_text[:20]}",
        "metadata": calculate_transcript_metadata(transcript_text),
    }


def _entries(id_prefix, count):
    # id_prefix is 9 characters, so each video ID is 11.
    return [
        {
            "position": position,
            "video_id": f"{id_prefix}{position:02d}",
            "title": f"Video {position}",
            "url": f"https://www.youtube.com/watch?v={id_prefix}{position:02d}",
        }
        for position in range(1, count + 1)
    ]


def _collect(entries, fetch, collected=None, request_delay=0):
    return collect_playlist_transcripts(
        entries,
        fetch,
        clean_transcript_text,
        build_timestamped_transcript,
        calculate_transcript_metadata,
        get_transcript_error_message,
        collected=collected,
        request_delay=request_delay,
    )


def _segments(video_id):
    return [{"start": 0, "text": f"Transcript words for {video_id}."}]


def test_split_transcript_keeps_paragraphs():
    paragraphs = [" ".join([f"p{number}"] * 4) for number in range(5)]
    transcript_text = "\n\n".join(paragraphs)

    parts = split_transcript_into_parts(transcript_text, word_limit=10)
    assert parts == [
        "\n\n".join(paragraphs[0:2]),
        "\n\n".join(paragraphs[2:4]),
        paragraphs[4],
    ]
    assert split_transcript_into_parts(transcript_text) == [transcript_text]

    long_paragraph = " ".join(["word"] * 25)
    parts = split_transcript_into_parts(long_paragraph, word_limit=10)
    assert [len(part.split()) for part in parts] == [10, 10, 5]


def test_describe_batch():
    units = build_playlist_units([_video(1, "aaaaaaaaaaa"), _video(2, "bbbbbbbbbbb")])
    assert describe_batch(units) == "videos 1–2"

    long_units = build_playlist_units([_video(7, "ccccccccccc", words=15)], word_limit=10)
    assert describe_batch(long_units[1:]) == "video 7, part 2 of 2"


def test_batch_prompt_caps_batch_synthesis():
    playlist_info = {"playlist_title": "Example Playlist", "playlist_id": "PL123456789012"}
    prompt = build_playlist_batch_prompt(
        playlist_info,
        build_playlist_units([_video(1, "aaaaaaaaaaa")]),
        1,
        1,
        "Study Notes",
        build_analysis_instructions("Study Notes"),
        1,
        1,
    )

    assert (
        f'section called "Batch synthesis" of at most {BATCH_SYNTHESIS_WORD_LIMIT} words'
        in prompt
    )


def test_synthesis_is_tiered_for_many_batches():
    playlist_info = {"playlist_title": "Example Playlist", "playlist_id": "PL123456789012"}

    assert plan_synthesis_groups(10) == []
    assert plan_synthesis_groups(25) == [(1, 10), (11, 20), (21, 25)]

    group_prompt = build_playlist_group_prompt(playlist_info, "Study Notes", 3, 3, 21, 25, 25)
    assert '[PASTE THE "Batch synthesis" SECTION FROM BATCH 21 HERE]' in group_prompt
    assert '[PASTE THE "Batch synthesis" SECTION FROM BATCH 25 HERE]' in group_prompt
    assert "FROM BATCH 20 HERE" not in group_prompt
    assert 'section called "Group synthesis"' in group_prompt

    final_prompt = build_playlist_synthesis_prompt(
        playlist_info,
        "Study Notes",
        successful_video_count=24,
        total_video_count=25,
        total_batches=25,
        failure_count=1,
        total_groups=3,
    )
    assert '[PASTE THE "Group synthesis" SECTION FROM GROUP 3 HERE]' in final_prompt
    assert "FROM BATCH" not in final_prompt


def test_playlist_outputs_for_large_playlist():
    videos = [_video(position, f"bigvideo{position:03d}", words=11000) for position in range(1, 26)]
    failure = {
        **_entries("missingvd", 26)[25],
        "title": 'Café, "quoted" title',
        "status": "not attempted",
        "error": NOT_ATTEMPTED_MESSAGE,
    }
    playlist_info = {
        "playlist_id": "PL123456789012",
        "playlist_title": "Example Playlist",
        "playlist_url": "https://www.youtube.com/playlist?list=PL123456789012",
        "entries": [{"video_id": video["video_id"]} for video in videos] + [failure],
    }

    outputs = build_playlist_outputs(
        playlist_info,
        videos,
        [failure],
        "Study Notes",
        build_analysis_instructions("Study Notes"),
    )

    assert len(outputs["batch_prompts"]) == 25
    assert outputs["batch_labels"][0] == "video 1"
    assert outputs["groups"] == [(1, 10), (11, 20), (21, 25)]
    assert len(outputs["group_prompts"]) == 3
    assert "FROM GROUP 3 HERE" in outputs["synthesis_prompt"]
    assert outputs["total_words"] == 25 * 11000

    assert outputs["manifest_csv"].startswith(b"\xef\xbb\xbf")
    manifest_rows = list(csv.DictReader(io.StringIO(outputs["manifest_csv"].decode("utf-8-sig"))))
    assert len(manifest_rows) == 26
    assert manifest_rows[-1]["title"] == 'Café, "quoted" title'
    assert manifest_rows[-1]["status"] == "not attempted"

    with zipfile.ZipFile(io.BytesIO(outputs["export_zip"])) as archive:
        names = set(archive.namelist())
        assert "prompts/batches/playlist_batch_025.txt" in names
        assert "prompts/groups/playlist_group_003.txt" in names
        assert "prompts/final_playlist_synthesis.txt" in names
        assert archive.read("playlist_manifest.csv") == outputs["manifest_csv"]
        assert "Group synthesis" in archive.read("README.txt").decode("utf-8")


def test_collect_stops_when_youtube_blocks():
    calls = []

    def fetch(video_id):
        calls.append(video_id)

        if video_id.endswith("03"):
            raise IpBlocked(video_id)

        return _segments(video_id)

    successful_videos, failures, blocked = _collect(_entries("blockvid0", 6), fetch)

    assert blocked
    assert len(calls) == 3
    assert [video["position"] for video in successful_videos] == [1, 2]
    assert [(failure["position"], failure["status"]) for failure in failures] == [
        (3, "failed"),
        (4, "not attempted"),
        (5, "not attempted"),
        (6, "not attempted"),
    ]
    assert failures[1]["error"] == NOT_ATTEMPTED_MESSAGE


def test_collect_records_network_errors_per_video():
    from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError

    def fetch(video_id):
        if video_id.endswith("02"):
            raise RequestsConnectionError("connection dropped")

        if video_id.endswith("03"):
            raise RequestsJSONDecodeError("Expecting value", "", 0)

        if video_id.endswith("04"):
            raise TranscriptsDisabled(video_id)

        return _segments(video_id)

    successful_videos, failures, blocked = _collect(_entries("netvideo0", 5), fetch)

    assert not blocked
    assert [video["position"] for video in successful_videos] == [1, 5]
    errors = {failure["position"]: failure["error"] for failure in failures}
    assert errors[2].startswith("Network error")
    assert errors[3].startswith("Network error")
    assert errors[4] == get_transcript_error_message(TranscriptsDisabled("netvideo004"))


def test_collect_reuses_collected_transcripts():
    import playlist_analysis

    calls = []

    def fetch(video_id):
        calls.append(video_id)
        return _segments(video_id)

    collected = {}
    _collect(_entries("reusevid0", 3), fetch, collected)
    assert len(calls) == 3
    assert len(collected) == 3

    sleeps = []
    original_sleep = playlist_analysis.time.sleep
    playlist_analysis.time.sleep = sleeps.append

    try:
        successful_videos, failures, blocked = _collect(
            _entries("reusevid0", 5), fetch, collected, request_delay=5
        )
    finally:
        playlist_analysis.time.sleep = original_sleep

    # Only videos 4 and 5 are downloaded, with one pause between them.
    assert calls[3:] == ["reusevid004", "reusevid005"]
    assert sleeps == [5]
    assert len(successful_videos) == 5
    assert not failures and not blocked

    def blocked_fetch(video_id):
        raise IpBlocked(video_id)

    successful_videos, failures, blocked = _collect(
        _entries("reusevid0", 6), blocked_fetch, collected
    )
    assert blocked
    assert len(successful_videos) == 5
    assert [(failure["position"], failure["status"]) for failure in failures] == [(6, "failed")]


PLAYLIST_UI_SCRIPT = """
import streamlit as st
from youtube_transcript_api import IpBlocked

from app import (
    PROMPT_MODES,
    build_analysis_instructions,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    clean_transcript_text,
    get_transcript_error_message,
)
from playlist_analysis import render_playlist_mode


def fake_playlist(user_input):
    playlist_id = user_input.strip()

    return {
        "playlist_id": playlist_id,
        "playlist_title": f"Title {playlist_id}",
        "playlist_url": f"https://www.youtube.com/playlist?list={playlist_id}",
        "entries": [
            {
                "position": position,
                "video_id": f"{playlist_id[:9]}{position:02d}",
                "title": f"Video {position}",
                "url": "https://www.youtube.com/",
            }
            for position in (1, 2, 3)
        ],
    }


def fake_fetch(video_id):
    st.session_state["fake_fetches"] = st.session_state.get("fake_fetches", 0) + 1

    if video_id == "PLBLOCKED02":
        raise IpBlocked(video_id)

    return [{"start": 0, "text": f"Transcript of {video_id}."}]


render_playlist_mode(
    PROMPT_MODES,
    fake_fetch,
    clean_transcript_text,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    get_transcript_error_message,
    build_analysis_instructions,
    playlist_fetcher=fake_playlist,
    request_delay=0,
)
"""


def _batch_prompt_text(app_test):
    return next(area.value for area in app_test.text_area if area.label.startswith("Batch "))


def test_playlist_ui_shows_prompts_for_current_playlist_and_mode():
    app_test = AppTest.from_string(PLAYLIST_UI_SCRIPT, default_timeout=60).run()

    app_test.text_input[0].input("PLAAAAAAAAAAAA").run()
    app_test.button[0].click().run()
    assert not app_test.exception
    assert "Title PLAAAAAAAAAAAA" in _batch_prompt_text(app_test)
    assert app_test.session_state["fake_fetches"] == 3

    # Changing the prompt mode rebuilds the prompts without fetching again.
    app_test.selectbox(key="playlist_prompt_mode_select").set_value("Action Plan").run()
    assert "Selected prompt mode: Action Plan" in _batch_prompt_text(app_test)
    assert app_test.session_state["fake_fetches"] == 3

    # A second playlist replaces the copy box contents, not just the downloads.
    app_test.text_input[0].input("PLBBBBBBBBBBBB").run()
    app_test.button[0].click().run()
    batch_text = _batch_prompt_text(app_test)
    assert "Title PLBBBBBBBBBBBB" in batch_text
    assert "Title PLAAAAAAAAAAAA" not in batch_text
    assert app_test.session_state["fake_fetches"] == 6

    # Re-analyzing the first playlist reuses its collected transcripts.
    app_test.text_input[0].input("PLAAAAAAAAAAAA").run()
    app_test.button[0].click().run()
    assert app_test.session_state["fake_fetches"] == 6

    app_test.text_input[0].input("PLBLOCKEDLIST1").run()
    app_test.button[0].click().run()
    assert not app_test.exception
    assert app_test.session_state["fake_fetches"] == 8
    assert any("blocking transcript requests" in warning.value for warning in app_test.warning)


def test_single_video_mode_works_without_yt_dlp():
    script = f"""
import sys
sys.modules["yt_dlp"] = None

import app
assert "playlist_analysis" not in sys.modules, "app.py must not import playlist code at startup"

from streamlit.testing.v1 import AppTest
app_test = AppTest.from_file({str(PROJECT_DIR / "app.py")!r}, default_timeout=60).run()
assert not app_test.exception, app_test.exception
assert app_test.text_input[0].label == "YouTube URL"

app_test.radio[0].set_value("Whole playlist").run()
assert not app_test.exception, app_test.exception
assert any("Whole-playlist mode is unavailable" in error.value for error in app_test.error)
print("single-video mode ok without yt-dlp")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "single-video mode ok without yt-dlp" in result.stdout


def main():
    test_extract_video_id()
    test_slugify_prompt_mode()
    test_calculate_transcript_metadata()
    test_split_transcript_into_chunks()
    test_format_timestamp()
    test_build_timestamped_transcript()
    test_build_chatgpt_analysis_prompt_includes_title()
    test_build_chunked_chatgpt_prompt()
    test_extract_playlist_id()
    test_playlist_batching_preserves_video_attribution()
    test_playlist_synthesis_prompt_mentions_missing_evidence()
    test_split_transcript_keeps_paragraphs()
    test_describe_batch()
    test_batch_prompt_caps_batch_synthesis()
    test_synthesis_is_tiered_for_many_batches()
    test_playlist_outputs_for_large_playlist()
    test_collect_stops_when_youtube_blocks()
    test_collect_records_network_errors_per_video()
    test_collect_reuses_collected_transcripts()
    test_playlist_ui_shows_prompts_for_current_playlist_and_mode()
    test_single_video_mode_works_without_yt_dlp()

    print("All manual regression checks passed.")


if __name__ == "__main__":
    main()
