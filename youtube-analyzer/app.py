import json
import re
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import streamlit as st
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
    YouTubeRequestFailed,
    VideoUnavailable,
)


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
PROMPT_MODES = [
    "General Analysis",
    "Study Notes",
    "Technical / Engineering Review",
    "Action Plan",
]
LONG_TRANSCRIPT_WORD_LIMIT = 20000
CHUNK_WORD_LIMIT = 12000


def extract_video_id(user_input):
    """Extract a YouTube video ID from a URL or direct video ID.

    This keeps the rest of the app focused on one clean video ID instead of
    handling many different YouTube URL shapes everywhere.
    """
    cleaned_input = user_input.strip()

    if not cleaned_input:
        return None

    # A raw YouTube video ID is usually 11 characters long.
    if VIDEO_ID_PATTERN.match(cleaned_input):
        return cleaned_input

    # urlparse needs a scheme to correctly recognize schemeless domains.
    if cleaned_input.startswith(("youtube.com/", "www.youtube.com/", "m.youtube.com/", "youtu.be/")):
        cleaned_input = f"https://{cleaned_input}"

    parsed_url = urlparse(cleaned_input)
    hostname = parsed_url.netloc.lower()
    path_parts = [part for part in parsed_url.path.split("/") if part]

    # Handle URLs like: https://www.youtube.com/watch?v=VIDEO_ID
    if hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        query_values = parse_qs(parsed_url.query)
        video_ids = query_values.get("v")

        if video_ids and VIDEO_ID_PATTERN.match(video_ids[0]):
            return video_ids[0]

        # Handle URLs like: https://youtube.com/shorts/VIDEO_ID
        # Also supports /embed/VIDEO_ID and /v/VIDEO_ID.
        if len(path_parts) >= 2 and path_parts[0] in ("shorts", "embed", "v"):
            video_id = path_parts[1]

            if VIDEO_ID_PATTERN.match(video_id):
                return video_id

    # Handle URLs like: https://youtu.be/VIDEO_ID
    if hostname in ("youtu.be", "www.youtu.be"):
        video_id = path_parts[0] if path_parts else ""

        if VIDEO_ID_PATTERN.match(video_id):
            return video_id

    # Invalid non-URL and non-ID input falls through to None.
    return None


@st.cache_data(ttl=3600)
def fetch_video_title(video_id):
    """Fetch the YouTube video title with oEmbed using only the standard library."""
    oembed_url = (
        "https://www.youtube.com/oembed"
        f"?url=https://www.youtube.com/watch?v={video_id}&format=json"
    )

    try:
        with urlopen(oembed_url, timeout=10) as response:
            video_data = json.load(response)

        return video_data.get("title", "Unknown title")
    except (OSError, URLError, json.JSONDecodeError):
        return "Unknown title"


@st.cache_data(ttl=3600)
def fetch_transcript_segments(video_id):
    """Fetch English transcript segments from YouTube.

    YouTube returns transcripts as many small timed segments. Keeping this
    function separate makes it easier to report the segment count in debug info.
    """
    transcript_api = YouTubeTranscriptApi()
    transcript = transcript_api.fetch(video_id, languages=("en",))

    return list(transcript)


def format_timestamp(seconds):
    """Format seconds as MM:SS or HH:MM:SS for transcript timestamps."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60

    if hours:
        return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"

    return f"{minutes:02}:{remaining_seconds:02}"


def get_transcript_segment_text(transcript_item):
    """Read transcript text from a transcript segment object or dictionary."""
    if isinstance(transcript_item, dict):
        return transcript_item.get("text", "")

    return transcript_item.text


def get_transcript_segment_start(transcript_item):
    """Read transcript start time from a transcript segment object or dictionary."""
    if isinstance(transcript_item, dict):
        return transcript_item.get("start", 0)

    return transcript_item.start


def build_timestamped_transcript(segments):
    """Build transcript text with each segment's start timestamp."""
    timestamped_lines = []

    for transcript_item in segments:
        start_time = get_transcript_segment_start(transcript_item)
        segment_text = re.sub(r"\s+", " ", get_transcript_segment_text(transcript_item)).strip()

        if segment_text:
            timestamped_lines.append(f"[{format_timestamp(start_time)}] {segment_text}")

    return "\n".join(timestamped_lines)


def clean_transcript_text(transcript_segments):
    """Turn transcript segments into readable paragraphs.

    This removes repeated whitespace and groups sentences into short paragraphs
    without changing the transcript's words.
    """
    cleaned_segments = []

    for transcript_item in transcript_segments:
        cleaned_text = re.sub(r"\s+", " ", get_transcript_segment_text(transcript_item)).strip()

        if cleaned_text:
            cleaned_segments.append(cleaned_text)

    combined_text = " ".join(cleaned_segments)
    combined_text = re.sub(r"\s+", " ", combined_text).strip()

    sentences = re.split(r"(?<=[.!?])\s+", combined_text)
    paragraphs = []
    current_paragraph = []

    for sentence in sentences:
        if not sentence:
            continue

        current_paragraph.append(sentence)

        paragraph_text = " ".join(current_paragraph)

        if len(paragraph_text) >= 500:
            paragraphs.append(paragraph_text)
            current_paragraph = []

    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))

    return "\n\n".join(paragraphs)


def calculate_transcript_metadata(transcript_text):
    """Calculate basic transcript metadata for display."""
    word_count = len(transcript_text.split())
    reading_time = max(1, round(word_count / 200))

    return {
        "character_count": len(transcript_text),
        "word_count": word_count,
        "reading_time": reading_time,
    }


def slugify_prompt_mode(prompt_mode):
    """Convert a prompt mode label into a safe filename slug."""
    return (
        prompt_mode.lower()
        .replace(" / ", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )


def build_analysis_instructions(prompt_mode):
    """Build analysis instructions for the selected prompt mode."""
    if prompt_mode == "Study Notes":
        return """Use the following structure:

1. Concise overview
2. Core concepts
3. Definitions and terminology
4. Key examples
5. Important quotes or moments
6. Study questions
7. Memory aids
8. Things to review again
9. Short final recap

Analysis instructions:
- Turn the transcript into clear study notes.
- Keep the notes organized and easy to review later.
- Explain important ideas in plain language.
- Preserve useful examples from the transcript.
- Call out confusing or unsupported points that need more review."""

    if prompt_mode == "Technical / Engineering Review":
        return """Use the following structure:

1. Technical summary
2. Main technical claims
3. Architecture, systems, or workflow described
4. Implementation details
5. Risks, tradeoffs, and constraints
6. Missing information
7. Things to verify
8. Engineering action items
9. Final technical assessment

Analysis instructions:
- Focus on technical accuracy and implementation relevance.
- Separate confirmed transcript details from assumptions.
- Identify risks, edge cases, and missing context.
- Flag claims that need independent verification.
- Keep the final assessment practical and specific."""

    if prompt_mode == "Action Plan":
        return """Use the following structure:

1. Goal summary
2. Main recommendations
3. Key decisions to make
4. Step-by-step action plan
5. Required resources
6. Risks and blockers
7. Things to verify
8. Next actions
9. Final priority list

Analysis instructions:
- Convert the transcript into a practical action plan.
- Make the steps concrete and ordered.
- Separate immediate actions from later actions.
- Identify dependencies, blockers, and verification steps.
- Keep the final priorities realistic."""

    return """Use the following structure:

1. Executive summary
2. Main argument or thesis
3. Key points
4. Important quotes or moments
5. Hidden assumptions
6. Practical takeaways
7. Things to verify
8. Action items
9. Final verdict

Analysis instructions:
- Be specific and grounded in the transcript.
- Separate facts from interpretations.
- Call out uncertainty when the transcript does not provide enough evidence.
- Identify any claims that should be independently verified.
- Keep the final verdict balanced and practical."""


def build_chatgpt_analysis_prompt(video_id, metadata, transcript_text, prompt_mode, video_title="Unknown title"):
    """Build a copy-and-paste prompt for manual ChatGPT analysis.

    This does not call the OpenAI API. It only prepares text the user can copy.
    """
    analysis_instructions = build_analysis_instructions(prompt_mode)

    return f"""Please analyze this YouTube video transcript.

Video title: {video_title}
Video ID: {video_id}
Transcript character count: {metadata["character_count"]}
Approximate word count: {metadata["word_count"]}
Approximate reading time: {metadata["reading_time"]} minute(s)
Selected prompt mode: {prompt_mode}

{analysis_instructions}

Full cleaned transcript:
The transcript text below is cleaned for readability. A timestamped transcript is also available separately in the app.

{transcript_text}
"""


def split_transcript_into_chunks(transcript_text, chunk_word_limit=CHUNK_WORD_LIMIT):
    """Split a long transcript into word-based chunks for safer manual prompting."""
    words = transcript_text.split()
    chunks = []

    for start_index in range(0, len(words), chunk_word_limit):
        chunk_words = words[start_index:start_index + chunk_word_limit]
        chunks.append(" ".join(chunk_words))

    return chunks


def build_chunked_chatgpt_prompt(
    video_id,
    metadata,
    chunk_text,
    chunk_number,
    total_chunks,
    prompt_mode,
    video_title="Unknown title",
):
    """Build one prompt for one chunk of a larger transcript."""
    analysis_instructions = build_analysis_instructions(prompt_mode)
    chunk_metadata = calculate_transcript_metadata(chunk_text)

    return f"""Please analyze this chunk of a larger YouTube video transcript.

Important context:
- This is chunk {chunk_number} of {total_chunks}.
- Do not treat this chunk as the complete transcript.
- Focus on this chunk while preserving notes that may be useful when combined with other chunks.
- The metadata below separates whole-transcript context from the current chunk size.

Video title: {video_title}
Video ID: {video_id}
Chunk: {chunk_number} of {total_chunks}
Selected prompt mode: {prompt_mode}

Whole transcript metadata:
- Total character count: {metadata["character_count"]}
- Total word count: {metadata["word_count"]}
- Estimated total reading time: {metadata["reading_time"]} minute(s)

Current chunk metadata:
- Chunk character count: {chunk_metadata["character_count"]}
- Chunk word count: {chunk_metadata["word_count"]}

{analysis_instructions}

Chunk transcript text:
The transcript text below is cleaned for readability. A timestamped transcript is also available separately in the app.

{chunk_text}
"""


def get_transcript_error_message(error):
    """Convert common transcript errors into clear Streamlit messages."""
    if isinstance(error, TranscriptsDisabled):
        return "Transcript disabled: this video does not allow transcript access."

    if isinstance(error, NoTranscriptFound):
        return "No English transcript found for this video."

    if isinstance(error, VideoUnavailable):
        return "Transcript unavailable: this video is unavailable or cannot be accessed."

    if isinstance(error, (YouTubeRequestFailed, RequestBlocked, IpBlocked)):
        return "Network or YouTube request failure: please check your connection and try again."

    if isinstance(error, CouldNotRetrieveTranscript):
        return "Transcript unavailable: YouTube did not return a usable transcript for this video."

    return f"Unknown transcript error: {error}"


def main():
    """Show the Streamlit app UI."""
    # Show the page title at the top of the app.
    st.title("YouTube Video Analyzer")

    # Ask the user to paste a YouTube video URL.
    youtube_url = st.text_input("YouTube URL")
    has_youtube_url = bool(youtube_url.strip())

    # Choose the kind of ChatGPT prompt to generate after transcript cleanup.
    prompt_mode = st.selectbox("Prompt mode", PROMPT_MODES)
    prompt_mode_slug = slugify_prompt_mode(prompt_mode)
    st.write(f"Selected prompt mode: {prompt_mode}")

    # When the button is clicked, try to fetch and display the transcript.
    if st.button("Analyze", disabled=not has_youtube_url):
        video_id = extract_video_id(youtube_url)
        transcript_segment_count = None

        if not video_id:
            st.error("Invalid YouTube URL or video ID. Please paste a supported YouTube URL or an 11-character video ID.")
        else:
            try:
                with st.spinner("Fetching transcript..."):
                    video_title = fetch_video_title(video_id)
                    transcript_segments = fetch_transcript_segments(video_id)
                    transcript_segment_count = len(transcript_segments)
                    transcript_text = clean_transcript_text(transcript_segments)
                    timestamped_transcript = build_timestamped_transcript(transcript_segments)

                metadata = calculate_transcript_metadata(transcript_text)

                st.write(f"Title: {video_title}")
                st.write(f"Video ID: {video_id}")
                st.write(f"Transcript character count: {metadata['character_count']}")
                st.write(f"Approximate word count: {metadata['word_count']}")
                st.write(f"Approximate reading time: {metadata['reading_time']} minute(s)")

                if metadata["word_count"] > LONG_TRANSCRIPT_WORD_LIMIT:
                    st.warning(
                        "This transcript is very long. The generated ChatGPT prompt may exceed some model limits."
                    )

                st.subheader("Transcript Preview")
                st.write(transcript_text[:1000])

                with st.expander("Full Transcript"):
                    st.write(transcript_text)

                st.download_button(
                    label="Download Readable Transcript",
                    data=transcript_text,
                    file_name=f"transcript_{video_id}_readable.txt",
                    mime="text/plain",
                )

                with st.expander("Timestamped Transcript"):
                    st.text(timestamped_transcript)

                st.download_button(
                    label="Download Timestamped Transcript",
                    data=timestamped_transcript,
                    file_name=f"transcript_{video_id}_timestamped.txt",
                    mime="text/plain",
                )

                chatgpt_prompt = build_chatgpt_analysis_prompt(
                    video_id,
                    metadata,
                    transcript_text,
                    prompt_mode,
                    video_title=video_title,
                )

                st.subheader("ChatGPT Analysis Prompt")
                st.info(
                    "Copy or download this prompt, then paste it into ChatGPT for analysis. "
                    "This app does not send the transcript to any AI service."
                )
                st.text_area(
                    "Copy this prompt into ChatGPT",
                    value=chatgpt_prompt,
                    height=700,
                )
                st.download_button(
                    label="Download ChatGPT Prompt",
                    data=chatgpt_prompt,
                    file_name=f"chatgpt_prompt_{video_id}_{prompt_mode_slug}_full.txt",
                    mime="text/plain",
                )

                if metadata["word_count"] > LONG_TRANSCRIPT_WORD_LIMIT:
                    transcript_chunks = split_transcript_into_chunks(transcript_text)
                    total_chunks = len(transcript_chunks)

                    st.subheader("Chunked ChatGPT Prompts")
                    st.write(
                        "Use these smaller prompts one at a time if the full prompt is too large for ChatGPT."
                    )

                    for chunk_index, chunk_text in enumerate(transcript_chunks, start=1):
                        chunk_prompt = build_chunked_chatgpt_prompt(
                            video_id,
                            metadata,
                            chunk_text,
                            chunk_index,
                            total_chunks,
                            prompt_mode,
                            video_title=video_title,
                        )

                        with st.expander(f"Chunk {chunk_index} of {total_chunks}"):
                            st.text_area(
                                f"ChatGPT prompt part {chunk_index}",
                                value=chunk_prompt,
                                height=350,
                            )
                            st.download_button(
                                label=f"Download ChatGPT Prompt Part {chunk_index}",
                                data=chunk_prompt,
                                file_name=(
                                    f"chatgpt_prompt_{video_id}_{prompt_mode_slug}_"
                                    f"part_{chunk_index}_of_{total_chunks}.txt"
                                ),
                                mime="text/plain",
                                key=f"download_chunk_prompt_{chunk_index}",
                            )
            except YouTubeTranscriptApiException as error:
                st.error(get_transcript_error_message(error))

        with st.expander("Debug info"):
            st.write(f"Raw extracted video ID: {video_id}")
            st.write(f"Input URL: {youtube_url}")

            if transcript_segment_count is not None:
                st.write(f"Transcript segment count: {transcript_segment_count}")


if __name__ == "__main__":
    main()
