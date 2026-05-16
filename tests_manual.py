# This is a lightweight regression script, not a full production test suite.

from app import (
    CHUNK_WORD_LIMIT,
    build_analysis_instructions,
    build_chunked_chatgpt_prompt,
    build_chatgpt_analysis_prompt,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    extract_video_id,
    format_timestamp,
    slugify_prompt_mode,
    split_transcript_into_chunks,
)


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


def main():
    test_extract_video_id()
    test_slugify_prompt_mode()
    test_calculate_transcript_metadata()
    test_split_transcript_into_chunks()
    test_format_timestamp()
    test_build_timestamped_transcript()
    test_build_chatgpt_analysis_prompt_includes_title()
    test_build_chunked_chatgpt_prompt()

    print("All manual regression checks passed.")


if __name__ == "__main__":
    main()
