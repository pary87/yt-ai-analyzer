import re
from urllib.parse import parse_qs, urlparse

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

    if "/" not in cleaned_input and "?" not in cleaned_input:
        if VIDEO_ID_PATTERN.match(cleaned_input):
            return cleaned_input

        return None

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

    return None


@st.cache_data(ttl=3600)
def fetch_transcript_segments(video_id):
    """Fetch English transcript segments from YouTube.

    YouTube returns transcripts as many small timed segments. Keeping this
    function separate makes it easier to report the segment count in debug info.
    """
    transcript_api = YouTubeTranscriptApi()
    transcript = transcript_api.fetch(video_id, languages=("en",))

    return list(transcript)


def clean_transcript_text(transcript_segments):
    """Turn transcript segments into readable paragraphs.

    This removes repeated whitespace and groups sentences into short paragraphs
    without changing the transcript's words.
    """
    cleaned_segments = []

    for transcript_item in transcript_segments:
        cleaned_text = re.sub(r"\s+", " ", transcript_item.text).strip()

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


def build_chatgpt_analysis_prompt(video_id, metadata, transcript_text):
    """Build a copy-and-paste prompt for manual ChatGPT analysis.

    This does not call the OpenAI API. It only prepares text the user can copy.
    """
    return f"""Please analyze this YouTube video transcript.

Video ID: {video_id}
Transcript character count: {metadata["character_count"]}
Approximate word count: {metadata["word_count"]}
Approximate reading time: {metadata["reading_time"]} minute(s)

Use the following structure:

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
- Keep the final verdict balanced and practical.

Full cleaned transcript:

{transcript_text}
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

    # When the button is clicked, try to fetch and display the transcript.
    if st.button("Analyze"):
        video_id = extract_video_id(youtube_url)
        transcript_segment_count = None

        if not video_id:
            st.error("Invalid YouTube URL or video ID. Please paste a supported YouTube URL or an 11-character video ID.")
        else:
            try:
                with st.spinner("Fetching transcript..."):
                    transcript_segments = fetch_transcript_segments(video_id)
                    transcript_segment_count = len(transcript_segments)
                    transcript_text = clean_transcript_text(transcript_segments)

                metadata = calculate_transcript_metadata(transcript_text)

                st.write(f"Video ID: {video_id}")
                st.write(f"Transcript character count: {metadata['character_count']}")
                st.write(f"Approximate word count: {metadata['word_count']}")
                st.write(f"Approximate reading time: {metadata['reading_time']} minute(s)")

                if metadata["word_count"] > 20000:
                    st.warning(
                        "This transcript is very long. The generated ChatGPT prompt may exceed some model limits."
                    )

                st.subheader("Transcript Preview")
                st.write(transcript_text[:1000])

                with st.expander("Full Transcript"):
                    st.write(transcript_text)

                st.download_button(
                    label="Download transcript.txt",
                    data=transcript_text,
                    file_name="transcript.txt",
                    mime="text/plain",
                )

                chatgpt_prompt = build_chatgpt_analysis_prompt(
                    video_id,
                    metadata,
                    transcript_text,
                )

                st.subheader("ChatGPT Analysis Prompt")
                st.write("Copy this prompt and paste it into ChatGPT for analysis.")
                st.text_area(
                    "Copy this prompt into ChatGPT",
                    value=chatgpt_prompt,
                    height=700,
                )
                st.download_button(
                    label="Download ChatGPT Prompt",
                    data=chatgpt_prompt,
                    file_name="chatgpt_analysis_prompt.txt",
                    mime="text/plain",
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
