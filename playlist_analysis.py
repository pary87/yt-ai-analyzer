import csv
import io
import re
import time
import zipfile
from urllib.parse import parse_qs, urlparse

import streamlit as st
from requests.exceptions import RequestException
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, remove_terminal_sequences
from youtube_transcript_api import RequestBlocked, YouTubeTranscriptApiException


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{12,}$")
PLAYLIST_BATCH_WORD_LIMIT = 12000
# YouTube blocks networks that request transcripts too quickly. The pause is
# only taken before a real download; transcripts collected earlier are reused.
PLAYLIST_REQUEST_DELAY_SECONDS = 1.0
BATCH_SYNTHESIS_WORD_LIMIT = 250
GROUP_SYNTHESIS_WORD_LIMIT = 400
SYNTHESIS_GROUP_SIZE = 10
BLOCKED_MESSAGE = (
    "YouTube blocked transcript requests from this network (rate limit). "
    "Wait before trying again."
)
NOT_ATTEMPTED_MESSAGE = "Not attempted: collection stopped after YouTube blocked requests."
EMPTY_TRANSCRIPT_MESSAGE = "Transcript is empty."


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


class _YtDlpErrorLog:
    """Keep yt-dlp's error messages so the app can show why a playlist failed."""

    def __init__(self):
        self.errors = []

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        self.errors.append(message)


@st.cache_data(ttl=3600)
def fetch_playlist_info(user_input):
    """Fetch a flat playlist index without downloading video or audio."""
    playlist_id = extract_playlist_id(user_input)
    playlist_url = normalize_playlist_url(user_input)

    if not playlist_id or not playlist_url:
        raise ValueError("Invalid YouTube playlist URL or playlist ID.")

    error_log = _YtDlpErrorLog()
    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "logger": error_log,
        "color": "no_color",
    }

    with YoutubeDL(options) as ydl:
        playlist_data = ydl.extract_info(playlist_url, download=False)

    if not playlist_data:
        reason = (
            remove_terminal_sequences(error_log.errors[-1])
            if error_log.errors
            else "no details from yt-dlp"
        )
        raise DownloadError(f"YouTube did not return playlist metadata ({reason}).")

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


def split_transcript_into_parts(text, word_limit=PLAYLIST_BATCH_WORD_LIMIT):
    """Split a transcript into parts of at most word_limit words.

    Paragraphs stay intact; only a single paragraph longer than the limit is
    split mid-paragraph.
    """
    parts = []
    current_paragraphs = []
    current_words = 0

    for paragraph in text.split("\n\n"):
        paragraph_words = len(paragraph.split())

        if not paragraph_words:
            continue

        pieces = [paragraph] if paragraph_words <= word_limit else _split_words(paragraph, word_limit)

        for piece in pieces:
            piece_words = len(piece.split())

            if current_paragraphs and current_words + piece_words > word_limit:
                parts.append("\n\n".join(current_paragraphs))
                current_paragraphs = []
                current_words = 0

            current_paragraphs.append(piece)
            current_words += piece_words

    if current_paragraphs:
        parts.append("\n\n".join(current_paragraphs))

    return parts


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
        chunks = split_transcript_into_parts(video["transcript_text"], word_limit)
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


def describe_batch(batch_units):
    """Describe which playlist videos a batch covers, e.g. 'videos 4–6'."""
    first_unit = batch_units[0]
    last_unit = batch_units[-1]

    if first_unit["position"] != last_unit["position"]:
        return f"videos {first_unit['position']}–{last_unit['position']}"

    description = f"video {first_unit['position']}"

    if first_unit["total_parts"] > 1:
        description += f", part {first_unit['part_number']} of {first_unit['total_parts']}"

    return description


def plan_synthesis_groups(total_batches, group_size=SYNTHESIS_GROUP_SIZE):
    """Plan the middle synthesis step as (first_batch, last_batch) ranges.

    Returns an empty list when the final prompt can take every batch synthesis
    directly. Otherwise the batches are split into as few groups of at most
    group_size as possible, with sizes differing by at most one, so no group
    holds a lone leftover batch.
    """
    if total_batches <= group_size:
        return []

    group_count = -(-total_batches // group_size)
    base_size, larger_groups = divmod(total_batches, group_count)
    groups = []
    first_batch = 1

    for group_index in range(group_count):
        size = base_size + (1 if group_index < larger_groups else 0)
        groups.append((first_batch, first_batch + size - 1))
        first_batch += size

    return groups


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
- End with a section called "Batch synthesis" of at most {BATCH_SYNTHESIS_WORD_LIMIT} words. Only that section is carried into the playlist synthesis, so make it self-contained and name the playlist videos behind each point.
- Do not invent content for playlist videos that are not present in this batch.

{analysis_instructions}

Playlist transcript batch:

{batch_text}
"""


def build_playlist_group_prompt(
    playlist_info,
    prompt_mode,
    group_number,
    total_groups,
    first_batch,
    last_batch,
    total_batches,
):
    """Build a prompt that combines the batch syntheses of one group of batches."""
    placeholders = "\n\n".join(
        f'[PASTE THE "Batch synthesis" SECTION FROM BATCH {batch_number} HERE]'
        for batch_number in range(first_batch, last_batch + 1)
    )

    return f"""Combine these batch syntheses from one part of a larger YouTube playlist.

Playlist title: {playlist_info["playlist_title"]}
Playlist ID: {playlist_info["playlist_id"]}
Group: {group_number} of {total_groups} (batches {first_batch}–{last_batch} of {total_batches})
Selected prompt mode: {prompt_mode}

Instructions:
- Use only the batch syntheses pasted below. Do not invent content for other parts of the playlist.
- Keep track of which playlist videos each point comes from.
- Note recurring themes, how ideas develop across these batches, and any tensions or contradictions.
- End with a section called "Group synthesis" of at most {GROUP_SYNTHESIS_WORD_LIMIT} words. Only that section is carried into the final playlist synthesis.

=== BATCH SYNTHESES START ===

{placeholders}

=== BATCH SYNTHESES END ===
"""


def build_playlist_synthesis_prompt(
    playlist_info,
    prompt_mode,
    successful_video_count,
    total_video_count,
    total_batches,
    failure_count,
    total_groups=0,
    missing_videos=(),
):
    """Build the final prompt used after every batch (and group) is analyzed.

    missing_videos lists the failed or not-attempted videos, so the synthesis
    can name the gaps in its evidence instead of guessing them.
    """
    if total_groups:
        source = "group syntheses"
        placeholders = "\n\n".join(
            f'[PASTE THE "Group synthesis" SECTION FROM GROUP {group_number} HERE]'
            for group_number in range(1, total_groups + 1)
        )
        group_line = f"\nGroup syntheses: {total_groups}"
    else:
        source = "batch syntheses"
        placeholders = "\n\n".join(
            f'[PASTE THE "Batch synthesis" SECTION FROM BATCH {batch_number} HERE]'
            for batch_number in range(1, total_batches + 1)
        )
        group_line = ""

    missing_list = "\n".join(
        f"- Video {video['position']}: {video['title']} ({video['status']})"
        for video in missing_videos
    ) or "- None"

    return f"""Create a whole-playlist synthesis from the {source} pasted below.

Playlist title: {playlist_info["playlist_title"]}
Playlist ID: {playlist_info["playlist_id"]}
Videos discovered: {total_video_count}
Videos with usable English transcripts: {successful_video_count}
Videos skipped or failed: {failure_count}
Transcript-analysis batches: {total_batches}{group_line}
Selected analysis mode: {prompt_mode}

Use the {source} as your evidence. Do not claim to have analyzed videos that were skipped or failed.

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
10. A video-by-video index of the most important contribution from each analyzed video, as far as the syntheses allow
11. Final synthesis

When evidence is missing because a transcript failed, say so explicitly.

Videos without a usable transcript (no evidence available):
{missing_list}

=== {source.upper()} START ===

{placeholders}

=== {source.upper()} END ===
"""


def build_playlist_manifest_csv(successful_videos, failures):
    """Create a CSV manifest recording the outcome for every discovered video."""
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
                "status": failure["status"],
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


def encode_csv_for_excel(csv_text):
    """Encode CSV as UTF-8 with a byte-order mark so Excel shows non-ASCII titles correctly."""
    return csv_text.encode("utf-8-sig")


def build_playlist_export_zip(
    playlist_info,
    successful_videos,
    failures,
    batch_prompts,
    group_prompts,
    synthesis_prompt,
):
    """Create a portable ZIP containing transcripts, prompts, and status evidence."""
    archive_buffer = io.BytesIO()

    if group_prompts:
        workflow_steps = (
            "1. Analyze prompts/batches in numerical order, each in a new chat.\n"
            '2. Save the "Batch synthesis" section of each ChatGPT response.\n'
            "3. Paste those sections into the matching prompts/groups prompt and\n"
            '   save the "Group synthesis" section of each response.\n'
            '4. Paste every "Group synthesis" section into\n'
            "   prompts/final_playlist_synthesis.txt.\n"
        )
    else:
        workflow_steps = (
            "1. Analyze prompts/batches in numerical order, each in a new chat.\n"
            '2. Save the "Batch synthesis" section of each ChatGPT response.\n'
            '3. Paste every "Batch synthesis" section into\n'
            "   prompts/final_playlist_synthesis.txt.\n"
        )

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
                f"{workflow_steps}\n"
                "The analyzer did not send transcript text to an AI service.\n"
            ),
        )
        archive.writestr(
            "playlist_manifest.csv",
            encode_csv_for_excel(build_playlist_manifest_csv(successful_videos, failures)),
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

        for group_number, group_prompt in enumerate(group_prompts, start=1):
            archive.writestr(
                f"prompts/groups/playlist_group_{group_number:03d}.txt",
                group_prompt,
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
                        f"{failure['title']} | {failure['status']} | {failure['error']}"
                    )
                    for failure in failures
                ),
            )

    return archive_buffer.getvalue()


def collect_playlist_transcripts(
    entries,
    fetch_transcript_segments,
    clean_transcript_text,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    get_transcript_error_message,
    collected=None,
    request_delay=PLAYLIST_REQUEST_DELAY_SECONDS,
    on_progress=None,
):
    """Collect an English transcript for each playlist entry, in order.

    `collected` maps video IDs to transcripts gathered earlier. Those videos are
    reused without a request, and each new success is added as soon as it
    arrives, so an interrupted or blocked run loses no finished work.

    Collection stops at the first sign that YouTube is blocking this network:
    every further request would fail and could prolong the block. Remaining
    videos that are not already collected are marked "not attempted".

    Returns (successful_videos, failures, blocked).
    """
    collected = {} if collected is None else collected
    successful_videos = []
    failures = []
    blocked = False
    has_fetched = False

    for index, entry in enumerate(entries, start=1):
        if on_progress:
            on_progress(index, len(entries), entry)

        transcript = collected.get(entry["video_id"])

        if transcript is not None:
            successful_videos.append({**entry, **transcript})
            continue

        if blocked:
            failures.append({**entry, "status": "not attempted", "error": NOT_ATTEMPTED_MESSAGE})
            continue

        if has_fetched and request_delay:
            time.sleep(request_delay)

        has_fetched = True

        try:
            transcript_segments = fetch_transcript_segments(entry["video_id"])
            transcript_text = clean_transcript_text(transcript_segments)
            transcript = {
                "transcript_text": transcript_text,
                "timestamped_transcript": build_timestamped_transcript(transcript_segments),
                "metadata": calculate_transcript_metadata(transcript_text),
            }
        except RequestBlocked:
            blocked = True
            failures.append({**entry, "status": "failed", "error": BLOCKED_MESSAGE})
            continue
        except YouTubeTranscriptApiException as error:
            failures.append(
                {**entry, "status": "failed", "error": get_transcript_error_message(error)}
            )
            continue
        except RequestException as error:
            failures.append({**entry, "status": "failed", "error": f"Network error: {error}"})
            continue
        except Exception as error:
            # One malformed response (for example an empty transcript XML body)
            # must not end the whole playlist run.
            failures.append(
                {
                    **entry,
                    "status": "failed",
                    "error": f"Unexpected error ({type(error).__name__}): {error}",
                }
            )
            continue

        if not transcript["metadata"]["word_count"]:
            failures.append({**entry, "status": "failed", "error": EMPTY_TRANSCRIPT_MESSAGE})
            continue

        collected[entry["video_id"]] = transcript
        successful_videos.append({**entry, **transcript})

    return successful_videos, failures, blocked


def build_playlist_outputs(
    playlist_info,
    successful_videos,
    failures,
    prompt_mode,
    analysis_instructions,
):
    """Build every prompt and export for one prompt mode from collected transcripts."""
    batches = split_playlist_units_into_batches(build_playlist_units(successful_videos))
    total_batches = len(batches)
    total_entries = len(playlist_info["entries"])

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
    groups = plan_synthesis_groups(total_batches)
    group_prompts = [
        build_playlist_group_prompt(
            playlist_info,
            prompt_mode,
            group_number,
            len(groups),
            first_batch,
            last_batch,
            total_batches,
        )
        for group_number, (first_batch, last_batch) in enumerate(groups, start=1)
    ]
    synthesis_prompt = build_playlist_synthesis_prompt(
        playlist_info,
        prompt_mode,
        len(successful_videos),
        total_entries,
        total_batches,
        len(failures),
        total_groups=len(groups),
        missing_videos=sorted(failures, key=lambda failure: failure["position"]),
    )

    return {
        "batch_prompts": batch_prompts,
        "batch_labels": [describe_batch(batch_units) for batch_units in batches],
        "groups": groups,
        "group_prompts": group_prompts,
        "synthesis_prompt": synthesis_prompt,
        "corpus": build_playlist_corpus(successful_videos),
        "manifest_csv": encode_csv_for_excel(
            build_playlist_manifest_csv(successful_videos, failures)
        ),
        "final_prompt_words_estimate": len(synthesis_prompt.split())
        + (
            len(groups) * GROUP_SYNTHESIS_WORD_LIMIT
            if groups
            else total_batches * BATCH_SYNTHESIS_WORD_LIMIT
        ),
        "total_words": sum(
            video["metadata"]["word_count"] for video in successful_videos
        ),
    }


@st.cache_resource
def _collected_transcripts():
    """Transcripts collected while the app runs, keyed by video ID.

    Kept at server level, not per browser session, so a page reload or a second
    tab reuses them instead of downloading (and pausing) again.
    """
    return {}


def _slugify(prompt_mode):
    return prompt_mode.lower().replace(" / ", "_").replace("/", "_").replace(" ", "_")


def _get_outputs(collection, prompt_mode, build_analysis_instructions):
    """Return outputs for the current collection and mode, building them once.

    Changing the prompt mode rebuilds prompts from the collected transcripts
    without fetching anything again.
    """
    key = (collection["run_id"], prompt_mode)
    outputs = st.session_state.get("playlist_outputs")

    if outputs is None or outputs["key"] != key:
        outputs = build_playlist_outputs(
            collection["playlist_info"],
            collection["successful_videos"],
            collection["failures"],
            prompt_mode,
            build_analysis_instructions(prompt_mode),
        )
        outputs["key"] = key
        st.session_state["playlist_outputs"] = outputs

    return outputs


def _render_prompt_picker(title, prompts, labels, key_prefix, file_prefix):
    """Show one prompt at a time with a picker, instead of every prompt at once."""
    total = len(prompts)

    if not total:
        return

    index = st.selectbox(
        title,
        range(total),
        format_func=lambda i: f"{i + 1} of {total} ({labels[i]})",
        key=f"{key_prefix}_select",
    )
    st.text_area(
        f"{title} {index + 1} of {total}",
        value=prompts[index],
        height=450,
        key=f"{key_prefix}_text_{index}",
    )
    st.download_button(
        f"Download {title.lower()} {index + 1}",
        data=prompts[index],
        file_name=f"{file_prefix}_{index + 1:03d}_of_{total:03d}.txt",
        mime="text/plain",
        key=f"{key_prefix}_download_{index}",
        on_click="ignore",
    )


def _render_result(collection, outputs, prompt_mode):
    playlist_info = collection["playlist_info"]
    successful_videos = collection["successful_videos"]
    failures = collection["failures"]
    playlist_id = playlist_info["playlist_id"]
    prompt_mode_slug = _slugify(prompt_mode)
    # Widget keys include the run and mode, so a new analysis or mode never
    # shows text left over from the previous one.
    key_prefix = f"playlist_{collection['run_id']}_{prompt_mode_slug}"
    batch_prompts = outputs["batch_prompts"]
    group_prompts = outputs["group_prompts"]

    st.subheader("Playlist Analysis")
    st.write(f"Playlist: {playlist_info['playlist_title']}")
    st.write(f"Playlist ID: {playlist_id}")
    st.write(f"Videos discovered: {len(playlist_info['entries'])}")
    st.write(f"Usable English transcripts: {len(successful_videos)}")
    st.write(f"Skipped or failed videos: {len(failures)}")
    st.write(f"Total transcript words: {outputs['total_words']:,}")

    if collection["blocked"]:
        not_attempted = sum(1 for failure in failures if failure["status"] == "not attempted")
        st.warning(
            "YouTube started blocking transcript requests from this network, so collection "
            f"stopped. {not_attempted} video(s) were not attempted. Collected transcripts are "
            "kept while the app is running: wait a while, then click Analyze Whole Playlist "
            "again to fetch only the missing videos."
        )
    elif failures:
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
            "Reason": "",
        }
        for video in successful_videos
    ]
    status_rows.extend(
        {
            "Position": failure["position"],
            "Status": failure["status"].capitalize(),
            "Title": failure["title"],
            "Words": None,
            "Reason": failure["error"],
        }
        for failure in failures
    )
    status_rows.sort(key=lambda row: row["Position"])

    with st.expander("Video transcript status", expanded=bool(failures)):
        st.dataframe(status_rows, hide_index=True)

    st.subheader("Downloads")
    st.download_button(
        "Download Playlist Manifest CSV",
        data=outputs["manifest_csv"],
        file_name=f"playlist_{playlist_id}_manifest.csv",
        mime="text/csv",
        on_click="ignore",
    )

    if not successful_videos or not batch_prompts:
        st.error("No usable English transcripts were collected from this playlist.")
        return

    st.download_button(
        "Download Full Playlist Transcript",
        data=outputs["corpus"],
        file_name=f"playlist_{playlist_id}_full_transcript.txt",
        mime="text/plain",
        on_click="ignore",
    )
    st.download_button(
        "Download Complete Playlist Analysis Package (.zip)",
        # Built only when clicked: compressing every transcript takes seconds
        # and is not needed for viewing prompts or switching modes.
        data=lambda: build_playlist_export_zip(
            playlist_info,
            successful_videos,
            failures,
            batch_prompts,
            group_prompts,
            outputs["synthesis_prompt"],
        ),
        file_name=f"playlist_{playlist_id}_{prompt_mode_slug}_analysis_package.zip",
        mime="application/zip",
        on_click="ignore",
    )

    rounds = len(batch_prompts) + len(group_prompts) + 1
    st.subheader("ChatGPT Prompts")
    st.info(
        f"This playlist takes {rounds} ChatGPT rounds: {len(batch_prompts)} batch prompt(s), "
        f"{len(group_prompts)} group prompt(s), and 1 final prompt. Use a new chat for each "
        'prompt and keep only the "synthesis" section of each answer for the next step.'
    )

    if outputs["final_prompt_words_estimate"] > PLAYLIST_BATCH_WORD_LIMIT:
        st.warning(
            "This playlist is very large: once filled in, the final prompt will be about "
            f"{outputs['final_prompt_words_estimate']:,} words, more than the "
            f"{PLAYLIST_BATCH_WORD_LIMIT:,}-word size used for batches. Consider analyzing "
            "the playlist in smaller parts."
        )

    st.markdown("**Step 1: Batch prompts**")
    _render_prompt_picker(
        "Batch",
        batch_prompts,
        outputs["batch_labels"],
        f"{key_prefix}_batch",
        f"playlist_{playlist_id}_{prompt_mode_slug}_batch",
    )

    if group_prompts:
        st.markdown("**Step 2: Group prompts**")
        st.caption(
            "Copy each group prompt into ChatGPT and replace each [PASTE ...] line with the "
            '"Batch synthesis" section from that batch. Text typed into the boxes here is not saved.'
        )
        _render_prompt_picker(
            "Group",
            group_prompts,
            [f"batches {first}–{last}" for first, last in outputs["groups"]],
            f"{key_prefix}_group",
            f"playlist_{playlist_id}_{prompt_mode_slug}_group",
        )

    final_source = "Group synthesis" if group_prompts else "Batch synthesis"
    st.markdown(f"**Step {3 if group_prompts else 2}: Final whole-playlist synthesis prompt**")
    st.text_area(
        f'Copy into ChatGPT and replace each [PASTE ...] line with that "{final_source}" section',
        value=outputs["synthesis_prompt"],
        height=500,
        key=f"{key_prefix}_final_text",
    )
    st.download_button(
        "Download Final Playlist Synthesis Prompt",
        data=outputs["synthesis_prompt"],
        file_name=f"playlist_{playlist_id}_{prompt_mode_slug}_final_synthesis.txt",
        mime="text/plain",
        on_click="ignore",
    )


def render_playlist_mode(
    prompt_modes,
    fetch_transcript_segments,
    clean_transcript_text,
    build_timestamped_transcript,
    calculate_transcript_metadata,
    get_transcript_error_message,
    build_analysis_instructions,
    playlist_fetcher=None,
    request_delay=PLAYLIST_REQUEST_DELAY_SECONDS,
):
    """Render whole-playlist analysis inside the parent Streamlit app."""
    playlist_fetcher = playlist_fetcher or fetch_playlist_info
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
        "English transcript for every playable video. Large playlists can take several minutes. "
        "No transcript is sent to an AI service; you paste the prompts into ChatGPT yourself."
    )

    if st.button("Analyze Whole Playlist", disabled=not has_input):
        if not extract_playlist_id(playlist_input):
            st.error(
                "Invalid YouTube playlist URL or playlist ID. Paste a playlist URL "
                "containing a valid list= value."
            )
        else:
            try:
                with st.spinner("Reading playlist..."):
                    playlist_info = playlist_fetcher(playlist_input)

                if not playlist_info["entries"]:
                    st.error("No playable videos were found in this playlist.")
                else:
                    progress = st.progress(0.0)
                    status = st.empty()

                    def show_progress(index, total, entry):
                        status.write(f"Collecting transcript {index} of {total}: {entry['title']}")
                        progress.progress(index / total)

                    # Cleared once the run finishes; still set on a later run means
                    # this one was interrupted (Streamlit stops a running script
                    # when a widget changes).
                    st.session_state["playlist_pending"] = playlist_info["playlist_title"]
                    successful_videos, failures, blocked = collect_playlist_transcripts(
                        playlist_info["entries"],
                        fetch_transcript_segments,
                        clean_transcript_text,
                        build_timestamped_transcript,
                        calculate_transcript_metadata,
                        get_transcript_error_message,
                        collected=_collected_transcripts(),
                        request_delay=request_delay,
                        on_progress=show_progress,
                    )
                    status.empty()
                    progress.empty()

                    run_id = st.session_state.get("playlist_run_id", 0) + 1
                    st.session_state["playlist_run_id"] = run_id
                    st.session_state["playlist_collection"] = {
                        "run_id": run_id,
                        "playlist_info": playlist_info,
                        "successful_videos": successful_videos,
                        "failures": failures,
                        "blocked": blocked,
                    }
                    st.session_state.pop("playlist_pending", None)
            except (DownloadError, ValueError) as error:
                st.error(f"Playlist error: {error}")

    interrupted_playlist = st.session_state.get("playlist_pending")

    if interrupted_playlist:
        st.warning(
            f'Collecting transcripts for "{interrupted_playlist}" was interrupted, usually '
            "because a setting changed while it ran. Transcripts collected so far are kept: "
            "click Analyze Whole Playlist to continue."
        )

    collection = st.session_state.get("playlist_collection")

    if collection:
        current_playlist_id = extract_playlist_id(playlist_input)

        if playlist_input.strip() and current_playlist_id != collection["playlist_info"]["playlist_id"]:
            st.info(
                "Showing results for the last analyzed playlist. Click Analyze Whole Playlist "
                "to analyze the playlist you entered."
            )

        _render_result(
            collection,
            _get_outputs(collection, prompt_mode, build_analysis_instructions),
            prompt_mode,
        )
