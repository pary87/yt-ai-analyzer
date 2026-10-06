import csv
import io
import re
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import streamlit as st
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from youtube_transcript_api import YouTubeTranscriptApiException


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{12,}$")
PLAYLIST_BATCH_WORD_LIMIT = 12000
PLAYLIST_REQUEST_DELAY_SECONDS = 0.15


def extract_playlist_id(user_input):
    """Extract a YouTube playlist ID from a URL or direct playlist ID."""
    cleaned_input = user_input.strip()

    if not cleaned_input:
        return None

    if PLAYLIST_ID_PATTERN.fullmatch(cleaned_input):
        return cleaned_input

    if cleaned_input.startswith(("youtube.com/", "www.youtube.com/", "m.youtube.com/")):
        cleaned_input = f"https://{cleaned_input}"

    parsed_url = urlparse(cleaned_input)
    hostname = parsed_url.netloc.lower()

    if hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        return None

    playlist_ids = parse_qs(parsed_url.query).get("list")

    if playlist_ids and PLAYLIST_ID_PATTERN.fullmatch(playlist_ids[0]):
        return playlist_ids[0]

    return None


def normalize_playlist_url(user_input):
    """Return a canonical YouTube playlist URL for valid playlist input."""
    playlist_id = extract_playlist_id(user_input)

    if not playlist_id:
        return None

    return f"https://www.youtube.com/playlist?list={playlist_id}"


@st.cache_data(ttl=3600)
def fetch_playlist_info(user_input):
    """Fetch a flat playlist index without downloading video or audio."""
    playlist_id = extract_playlist_id(user_input)
    playlist_url = normalize_playlist_url(user_input)

    if not playlist_id or not playlist_url:
        raise ValueError("Invalid YouTube playlist URL or playlist ID.")

    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    with YoutubeDL(options) as ydl:
        playlist_data = ydl.extract_info(playlist_url, download=False)

    if not playlist_data:
        raise DownloadError("YouTube did not return playlist metadata.")

    entries = []

    for position, entry in enumerate(playlist_data.get("entries") or [], start=1):
        if not entry:
            continue

        video_id = entry.get("id", "")

        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            continue

        entries.append(
            {
                "position": position,
                "video_id": video_id,
                "title": entry.get("title") or f"Video {position}",
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    return {
        "playlist_id": playlist_data.get("id") or playlist_id,
        "playlist_title": playlist_data.get("title") or f"Playlist {playlist_id}",
        "playlist_url": playlist_url,
        "entries": entries,
    }


def _split_words(text, word_limit=PLAYLIST_BATCH_WORD_LIMIT):
    words = text.split()

    return [
        " ".join(words[start:start + word_limit])
        for start in range(0, len(words), word_limit)
    ]


def build_playlist_corpus(successful_videos):
    """Combine playlist transcripts while keeping strong video boundaries."""
    sections = []

    for video in successful_videos:
        sections.append(
            f"""# Video {video["position"]}: {video["title"]}
Video ID: {video["video_id"]}
URL: {video["url"]}
Word count: {video["metadata"]["word_count"]}

{video["transcript_text"]}"""
        )

    return ("\n\n" + ("=" * 80) + "\n\n").join(sections)


def build_playlist_units(successful_videos, word_limit=PLAYLIST_BATCH_WORD_LIMIT):
    """Split long videos into units while preserving playlist/video attribution."""
    units = []

    for video in successful_videos:
        chunks = _split_words(video["transcript_text"], word_limit)
        total_parts = len(chunks)

        for part_number, chunk_text in enumerate(chunks, start=1):
            units.append(
                {
                    "position": video["position"],
                    "video_id": video["video_id"],
                    "title": video["title"],
                    "url": video["url"],
                    "part_number": part_number,
                    "total_parts": total_parts,
                    "text": chunk_text,
                    "word_count": len(chunk_text.split()),
                }
            )

    return units


def split_playlist_units_into_batches(units, word_limit=PLAYLIST_BATCH_WORD_LIMIT):
    """Group transcript units into prompt-sized batches."""
    batches = []
    current_batch = []
    current_words = 0

    for unit in units:
        unit_words = unit["word_count"]

        if current_batch and current_words + unit_words > word_limit:
            batches.append(current_batch)
            current_batch = []
            current_words = 0

        current_batch.append(unit)
        current_words += unit_words

    if current_batch:
        batches.append(current_batch)

    return batches


def build_playlist_batch_prompt(
    playlist_info,
    batch_units,
    batch_number,
    total_batches,
    prompt_mode,
    analysis_instructions,
    successful_video_count,
    total_video_count,
):
    """Build one manual ChatGPT prompt for a playlist transcript batch."""
    transcript_sections = []

    for unit in batch_units:
        part_label = ""

        if unit["total_parts"] > 1:
            part_label = (
                f" — transcript part {unit['part_number']} of {unit['total_parts']}"
            )

        transcript_sections.append(
            f"""## Playlist video {unit["position"]}: {unit["title"]}{part_label}
Video ID: {unit["video_id"]}
URL: {unit["url"]}

{unit["text"]}"""
        )

    batch_text = "\n\n---\n\n".join(transcript_sections)

    return f"""Analyze this batch from a larger YouTube playlist.

Playlist title: {playlist_info["playlist_title"]}
Playlist ID: {playlist_info["playlist_id"]}
Batch: {batch_number} of {total_batches}
Videos with usable transcripts: {successful_video_count} of {total_video_count}
Selected prompt mode: {prompt_mode}

Important workflow instructions:
- This is only one batch from the playlist. Do not treat it as the complete playlist.
- Preserve every video's title and playlist position in your notes.
- Analyze each included video or transcript part on its own before drawing cross-video conclusions.
- Track recurring themes, terminology, claims, disagreements, progression, and references to earlier/later material.
- End with a section called "Batch synthesis" that can be combined with the other batch syntheses later.
- Do not invent content for playlist videos that are not present in this batch.

{analysis_instructions}

Playlist transcript batch:

{batch_text}
"""


def build_playlist_synthesis_prompt(
    playlist_info,
    prompt_mode,
    successful_video_count,
    total_video_count,
    total_batches,
    failure_count,
):
    """Build the final prompt used after every playlist batch is analyzed."""
    placeholders = "\n".join(
        f"[PASTE BATCH {batch_number} ANALYSIS HERE]"
        for batch_number in range(1, total_batches + 1)
    )

    return f"""Create a whole-playlist synthesis from the batch analyses pasted below.

Playlist title: {playlist_info["playlist_title"]}
Playlist ID: {playlist_info["playlist_id"]}
Videos discovered: {total_video_count}
Videos with usable English transcripts: {successful_video_count}
Videos skipped or failed: {failure_count}
Transcript-analysis batches: {total_batches}
Selected analysis mode: {prompt_mode}

Use the batch analyses as your evidence. Do not claim to have analyzed videos that were skipped or failed.

Required whole-playlist synthesis:
1. Executive overview of the playlist
2. Main thesis, purpose, or teaching arc
3. How the ideas develop across the playlist
4. Recurring concepts and terminology
5. Important ideas that appear only in specific videos
6. Agreements, tensions, contradictions, or changes in emphasis
7. Strongest examples, explanations, and practical exercises
8. Claims or assumptions that deserve independent verification
9. Practical takeaways or study plan
10. A video-by-video index of the most important contribution from each analyzed video
11. Final synthesis

When evidence is missing because a transcript failed, say so explicitly.

=== BATCH ANALYSES START ===

{placeholders}

=== BATCH ANALYSES END ===
"""


def build_playlist_manifest_csv(successful_videos, failures):
    """Create a CSV manifest recording success/failure for every processed video."""
    rows = []

    for video in successful_videos:
        rows.append(
            {
                "position": video["position"],
                "status": "success",
                "title": video["title"],
                "video_id": video["video_id"],
                "url": video["url"],
                "word_count": video["metadata"]["word_count"],
                "error": "",
            }
        )

    for failure in failures:
        rows.append(
            {
                "position": failure["position"],
                "status": "failed",
                "title": failure["title"],
                "video_id": failure["video_id"],
                "url": failure["url"],
                "word_count": "",
                "error": failure["error"],
            }
        )

    rows.sort(key=lambda row: row["position"])
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "position",
            "status",
            "title",
            "video_id",
            "url",
            "word_count",
            "error",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    return output.getvalue()


def build_playlist_export_zip(
    playlist_info,
    successful_videos,
    failures,
    batch_prompts,
    synthesis_prompt,
):
    """Create a portable ZIP containing transcripts, prompts, and status evidence."""
    archive_buffer = io.BytesIO()

    with zipfile.ZipFile(
        archive_buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "README.txt",
            (
                "YouTube AI Analyzer playlist package\n\n"
                f"Playlist: {playlist_info['playlist_title']}\n"
                f"Playlist ID: {playlist_info['playlist_id']}\n\n"
                "Workflow:\n"
                "1. Analyze prompts/batches in numerical order.\n"
                "2. Save each ChatGPT response.\n"
                "3. Open prompts/final_playlist_synthesis.txt.\n"
                "4. Paste all completed batch analyses into that prompt.\n\n"
                "The analyzer did not send transcript text to an AI service.\n"
            ),
        )
        archive.writestr(
            "playlist_manifest.csv",
            build_playlist_manifest_csv(successful_videos, failures),
        )
        archive.writestr(
            "playlist_full_readable_transcript.txt",
            build_playlist_corpus(successful_videos),
        )
        archive.writestr(
            "prompts/final_playlist_synthesis.txt",
            synthesis_prompt,
        )

        for batch_number, batch_prompt in enumerate(batch_prompts, start=1):
            archive.writestr(
                f"prompts/batches/playlist_batch_{batch_number:03d}.txt",
                batch_prompt,
            )

        for video in successful_videos:
            prefix = f"{video['position']:03d}_{video['video_id']}"
            archive.writestr(
                f"transcripts/readable/{prefix}.txt",
                video["transcript_text"],
            )
            archive.writestr(
                f"transcripts/timestamped/{prefix}.txt",
                video["timestamped_transcript"],
            )

        if failures:
            archive.writestr(
                "failed_videos.txt",
                "\n".join(
                    (
                        f"{failure['position']:03d} | {failure['video_id']} | "
                        f"{failure['title']} | {failure['error']}"
                    )
                    for failure in failures
                ),
            )

    return archive_buffer.getvalue()


def _collect_playlist_transcripts(
    playlist_info,
    fetch_transcript_segments,
    clean_transcript_text,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    get_transcript_error_message,
):
    entries = playlist_info["entries"]

    if not entries:
        raise DownloadError("No playable videos were found in this playlist.")

    successful_videos = []
    failures = []
    total_entries = len(entries)
    progress = st.progress(0)
    status = st.empty()

    for index, entry in enumerate(entries, start=1):
        status.write(
            f"Fetching transcript {index} of {total_entries}: {entry['title']}"
        )

        try:
            transcript_segments = fetch_transcript_segments(entry["video_id"])
            transcript_text = clean_transcript_text(transcript_segments)
            timestamped_transcript = build_timestamped_transcript(transcript_segments)
            metadata = calculate_transcript_metadata(transcript_text)

            successful_videos.append(
                {
                    **entry,
                    "transcript_text": transcript_text,
                    "timestamped_transcript": timestamped_transcript,
                    "metadata": metadata,
                }
            )
        except YouTubeTranscriptApiException as error:
            failures.append(
                {
                    **entry,
                    "error": get_transcript_error_message(error),
                }
            )

        progress.progress(index / total_entries)

        if index < total_entries:
            time.sleep(PLAYLIST_REQUEST_DELAY_SECONDS)

    status.empty()
    progress.empty()

    return successful_videos, failures


def _build_result(
    playlist_info,
    successful_videos,
    failures,
    prompt_mode,
    build_analysis_instructions,
):
    units = build_playlist_units(successful_videos)
    batches = split_playlist_units_into_batches(units)
    total_batches = len(batches)
    total_entries = len(playlist_info["entries"])
    analysis_instructions = build_analysis_instructions(prompt_mode)

    batch_prompts = [
        build_playlist_batch_prompt(
            playlist_info,
            batch_units,
            batch_number,
            total_batches,
            prompt_mode,
            analysis_instructions,
            len(successful_videos),
            total_entries,
        )
        for batch_number, batch_units in enumerate(batches, start=1)
    ]

    synthesis_prompt = build_playlist_synthesis_prompt(
        playlist_info,
        prompt_mode,
        len(successful_videos),
        total_entries,
        total_batches,
        len(failures),
    )

    return {
        "playlist_info": playlist_info,
        "successful_videos": successful_videos,
        "failures": failures,
        "batch_prompts": batch_prompts,
        "synthesis_prompt": synthesis_prompt,
        "prompt_mode": prompt_mode,
        "total_words": sum(
            video["metadata"]["word_count"] for video in successful_videos
        ),
    }


def _render_result(result):
    playlist_info = result["playlist_info"]
    successful_videos = result["successful_videos"]
    failures = result["failures"]
    batch_prompts = result["batch_prompts"]
    synthesis_prompt = result["synthesis_prompt"]
    playlist_id = playlist_info["playlist_id"]
    prompt_mode_slug = (
        result["prompt_mode"]
        .lower()
        .replace(" / ", "_")
        .replace("/", "_")
        .replace(" ", "_")
    )

    st.subheader("Playlist Analysis Ready")
    st.write(f"Playlist: {playlist_info['playlist_title']}")
    st.write(f"Playlist ID: {playlist_id}")
    st.write(f"Videos discovered: {len(playlist_info['entries'])}")
    st.write(f"Usable English transcripts: {len(successful_videos)}")
    st.write(f"Skipped or failed videos: {len(failures)}")
    st.write(f"Total transcript words: {result['total_words']:,}")
    st.write(f"Generated ChatGPT batches: {len(batch_prompts)}")

    if failures:
        st.warning(
            "Some videos could not be included. The manifest and ZIP package record "
            "the exact failures so the final synthesis can distinguish missing evidence."
        )

    status_rows = [
        {
            "Position": video["position"],
            "Status": "Ready",
            "Title": video["title"],
            "Words": video["metadata"]["word_count"],
        }
        for video in successful_videos
    ]
    status_rows.extend(
        {
            "Position": failure["position"],
            "Status": "Failed",
            "Title": failure["title"],
            "Words": "",
        }
        for failure in failures
    )
    status_rows.sort(key=lambda row: row["Position"])

    with st.expander("Video transcript status", expanded=bool(failures)):
        st.dataframe(status_rows, use_container_width=True, hide_index=True)

    corpus = build_playlist_corpus(successful_videos)
    manifest_csv = build_playlist_manifest_csv(successful_videos, failures)
    export_zip = build_playlist_export_zip(
        playlist_info,
        successful_videos,
        failures,
        batch_prompts,
        synthesis_prompt,
    )

    st.subheader("Downloads")
    st.download_button(
        "Download Full Playlist Transcript",
        data=corpus,
        file_name=f"playlist_{playlist_id}_full_transcript.txt",
        mime="text/plain",
    )
    st.download_button(
        "Download Playlist Manifest CSV",
        data=manifest_csv,
        file_name=f"playlist_{playlist_id}_manifest.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download Complete Playlist Analysis Package (.zip)",
        data=export_zip,
        file_name=f"playlist_{playlist_id}_{prompt_mode_slug}_analysis_package.zip",
        mime="application/zip",
    )

    st.subheader("Batch Analysis Prompts")
    st.info(
        "Analyze these batch prompts in order. Each one produces a batch synthesis. "
        "After all batches are complete, use the final synthesis prompt below."
    )

    for batch_number, batch_prompt in enumerate(batch_prompts, start=1):
        with st.expander(
            f"Playlist batch {batch_number} of {len(batch_prompts)}",
            expanded=batch_number == 1,
        ):
            st.text_area(
                f"Copy playlist batch {batch_number}",
                value=batch_prompt,
                height=450,
                key=f"playlist_batch_text_{batch_number}",
            )
            st.download_button(
                f"Download Playlist Batch {batch_number}",
                data=batch_prompt,
                file_name=(
                    f"playlist_{playlist_id}_{prompt_mode_slug}_"
                    f"batch_{batch_number:03d}_of_{len(batch_prompts):03d}.txt"
                ),
                mime="text/plain",
                key=f"download_playlist_batch_{batch_number}",
            )

    st.subheader("Final Whole-Playlist Synthesis Prompt")
    st.text_area(
        "After completing all batch analyses, paste those results into this prompt",
        value=synthesis_prompt,
        height=650,
    )
    st.download_button(
        "Download Final Playlist Synthesis Prompt",
        data=synthesis_prompt,
        file_name=f"playlist_{playlist_id}_{prompt_mode_slug}_final_synthesis.txt",
        mime="text/plain",
    )


def render_playlist_mode(
    prompt_modes,
    fetch_transcript_segments,
    clean_transcript_text,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    get_transcript_error_message,
    build_analysis_instructions,
):
    """Render whole-playlist analysis inside the parent Streamlit app."""
    playlist_input = st.text_input(
        "YouTube playlist URL or playlist ID",
        placeholder="https://www.youtube.com/playlist?list=...",
    )
    prompt_mode = st.selectbox(
        "Playlist prompt mode",
        prompt_modes,
        key="playlist_prompt_mode_select",
    )
    has_input = bool(playlist_input.strip())

    st.caption(
        "Whole-playlist mode indexes the playlist, then attempts to collect an "
        "English transcript for every playable video. Large playlists can take several minutes."
    )

    if st.button("Analyze Whole Playlist", disabled=not has_input):
        if not extract_playlist_id(playlist_input):
            st.error(
                "Invalid YouTube playlist URL or playlist ID. Paste a playlist URL "
                "containing a valid list= value."
            )
        else:
            try:
                with st.spinner("Reading playlist and collecting transcripts..."):
                    playlist_info = fetch_playlist_info(playlist_input)
                    successful_videos, failures = _collect_playlist_transcripts(
                        playlist_info,
                        fetch_transcript_segments,
                        clean_transcript_text,
                        build_timestamped_transcript,
                        calculate_transcript_metadata,
                        get_transcript_error_message,
                    )

                    if not successful_videos:
                        st.error(
                            "No usable English transcripts were collected from this playlist."
                        )
                        st.session_state.pop("playlist_result", None)
                    else:
                        st.session_state["playlist_result"] = _build_result(
                            playlist_info,
                            successful_videos,
                            failures,
                            prompt_mode,
                            build_analysis_instructions,
                        )
            except (DownloadError, ValueError) as error:
                st.error(f"Playlist error: {error}")

    result = st.session_state.get("playlist_result")

    if result:
        _render_result(result)
