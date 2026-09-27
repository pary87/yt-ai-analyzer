// Transcript cleanup and prompt building, ported from app.py.
// Keep the prompt text in sync with app.py so both versions produce the same prompts.

export const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;
export const PROMPT_MODES = [
  "General Analysis",
  "Study Notes",
  "Technical / Engineering Review",
  "Action Plan",
];
export const LONG_TRANSCRIPT_WORD_LIMIT = 20000;
export const CHUNK_WORD_LIMIT = 12000;

const SCHEMELESS_PREFIXES = ["youtube.com/", "www.youtube.com/", "m.youtube.com/", "youtu.be/"];
const YOUTUBE_HOSTS = ["youtube.com", "www.youtube.com", "m.youtube.com"];
const SHORT_LINK_HOSTS = ["youtu.be", "www.youtu.be"];

/**
 * Extract a YouTube video ID from a URL or direct video ID.
 * Returns null when the input is not a supported YouTube URL or ID.
 */
export function extractVideoId(userInput) {
  let cleanedInput = (userInput || "").trim();

  if (!cleanedInput) {
    return null;
  }

  // A raw YouTube video ID is usually 11 characters long.
  if (VIDEO_ID_PATTERN.test(cleanedInput)) {
    return cleanedInput;
  }

  // URL parsing needs a scheme to correctly recognize schemeless domains.
  if (SCHEMELESS_PREFIXES.some((prefix) => cleanedInput.startsWith(prefix))) {
    cleanedInput = `https://${cleanedInput}`;
  }

  let parsedUrl;

  try {
    parsedUrl = new URL(cleanedInput);
  } catch {
    return null;
  }

  const hostname = parsedUrl.host.toLowerCase();
  const pathParts = parsedUrl.pathname.split("/").filter(Boolean);

  // Handle URLs like: https://www.youtube.com/watch?v=VIDEO_ID
  if (YOUTUBE_HOSTS.includes(hostname)) {
    const videoId = parsedUrl.searchParams.get("v");

    if (videoId && VIDEO_ID_PATTERN.test(videoId)) {
      return videoId;
    }

    // Handle URLs like: https://youtube.com/shorts/VIDEO_ID
    // Also supports /embed/VIDEO_ID and /v/VIDEO_ID.
    if (pathParts.length >= 2 && ["shorts", "embed", "v"].includes(pathParts[0])) {
      if (VIDEO_ID_PATTERN.test(pathParts[1])) {
        return pathParts[1];
      }
    }
  }

  // Handle URLs like: https://youtu.be/VIDEO_ID
  if (SHORT_LINK_HOSTS.includes(hostname)) {
    const videoId = pathParts[0] || "";

    if (VIDEO_ID_PATTERN.test(videoId)) {
      return videoId;
    }
  }

  return null;
}

/** Format seconds as MM:SS or HH:MM:SS for transcript timestamps. */
export function formatTimestamp(seconds) {
  const totalSeconds = Math.trunc(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;
  const pad = (value) => String(value).padStart(2, "0");

  if (hours) {
    return `${pad(hours)}:${pad(minutes)}:${pad(remainingSeconds)}`;
  }

  return `${pad(minutes)}:${pad(remainingSeconds)}`;
}

function collapseWhitespace(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

/** Split text on whitespace like Python's str.split(). */
function splitWords(text) {
  const trimmedText = text.trim();
  return trimmedText ? trimmedText.split(/\s+/) : [];
}

/** Build transcript text with each segment's start timestamp. */
export function buildTimestampedTranscript(segments) {
  const timestampedLines = [];

  for (const segment of segments) {
    const segmentText = collapseWhitespace(segment.text);

    if (segmentText) {
      timestampedLines.push(`[${formatTimestamp(segment.start || 0)}] ${segmentText}`);
    }
  }

  return timestampedLines.join("\n");
}

/**
 * Turn transcript segments into readable paragraphs.
 * This removes repeated whitespace and groups sentences into short paragraphs
 * without changing the transcript's words.
 */
export function cleanTranscriptText(segments) {
  const cleanedSegments = segments.map((segment) => collapseWhitespace(segment.text)).filter(Boolean);
  const combinedText = collapseWhitespace(cleanedSegments.join(" "));
  const sentences = combinedText.split(/(?<=[.!?])\s+/);
  const paragraphs = [];
  let currentParagraph = [];

  for (const sentence of sentences) {
    if (!sentence) {
      continue;
    }

    currentParagraph.push(sentence);

    if (currentParagraph.join(" ").length >= 500) {
      paragraphs.push(currentParagraph.join(" "));
      currentParagraph = [];
    }
  }

  if (currentParagraph.length) {
    paragraphs.push(currentParagraph.join(" "));
  }

  return paragraphs.join("\n\n");
}

/** Round like Python's round(): halfway values go to the nearest even number. */
function roundHalfToEven(value) {
  const floorValue = Math.floor(value);
  const difference = value - floorValue;

  if (difference > 0.5) {
    return floorValue + 1;
  }

  if (difference < 0.5) {
    return floorValue;
  }

  return floorValue % 2 === 0 ? floorValue : floorValue + 1;
}

/** Calculate basic transcript metadata for display. */
export function calculateTranscriptMetadata(transcriptText) {
  const wordCount = splitWords(transcriptText).length;

  return {
    characterCount: [...transcriptText].length,
    wordCount,
    readingTime: Math.max(1, roundHalfToEven(wordCount / 200)),
  };
}

/** Convert a prompt mode label into a safe filename slug. */
export function slugifyPromptMode(promptMode) {
  return promptMode.toLowerCase().replaceAll(" / ", "_").replaceAll("/", "_").replaceAll(" ", "_");
}

/** Build analysis instructions for the selected prompt mode. */
export function buildAnalysisInstructions(promptMode) {
  if (promptMode === "Study Notes") {
    return `Use the following structure:

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
- Call out confusing or unsupported points that need more review.`;
  }

  if (promptMode === "Technical / Engineering Review") {
    return `Use the following structure:

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
- Keep the final assessment practical and specific.`;
  }

  if (promptMode === "Action Plan") {
    return `Use the following structure:

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
- Keep the final priorities realistic.`;
  }

  return `Use the following structure:

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
- Keep the final verdict balanced and practical.`;
}

/**
 * Build a copy-and-paste prompt for manual ChatGPT analysis.
 * This does not call any AI service. It only prepares text the user can copy.
 */
export function buildChatgptAnalysisPrompt(videoId, metadata, transcriptText, promptMode, videoTitle = "Unknown title") {
  return `Please analyze this YouTube video transcript.

Video title: ${videoTitle}
Video ID: ${videoId}
Transcript character count: ${metadata.characterCount}
Approximate word count: ${metadata.wordCount}
Approximate reading time: ${metadata.readingTime} minute(s)
Selected prompt mode: ${promptMode}

${buildAnalysisInstructions(promptMode)}

Full cleaned transcript:
The transcript text below is cleaned for readability. A timestamped transcript is also available separately in the app.

${transcriptText}
`;
}

/** Split a long transcript into word-based chunks for safer manual prompting. */
export function splitTranscriptIntoChunks(transcriptText, chunkWordLimit = CHUNK_WORD_LIMIT) {
  const words = splitWords(transcriptText);
  const chunks = [];

  for (let startIndex = 0; startIndex < words.length; startIndex += chunkWordLimit) {
    chunks.push(words.slice(startIndex, startIndex + chunkWordLimit).join(" "));
  }

  return chunks;
}

/** Build one prompt for one chunk of a larger transcript. */
export function buildChunkedChatgptPrompt(
  videoId,
  metadata,
  chunkText,
  chunkNumber,
  totalChunks,
  promptMode,
  videoTitle = "Unknown title",
) {
  const chunkMetadata = calculateTranscriptMetadata(chunkText);

  return `Please analyze this chunk of a larger YouTube video transcript.

Important context:
- This is chunk ${chunkNumber} of ${totalChunks}.
- Do not treat this chunk as the complete transcript.
- Focus on this chunk while preserving notes that may be useful when combined with other chunks.
- The metadata below separates whole-transcript context from the current chunk size.

Video title: ${videoTitle}
Video ID: ${videoId}
Chunk: ${chunkNumber} of ${totalChunks}
Selected prompt mode: ${promptMode}

Whole transcript metadata:
- Total character count: ${metadata.characterCount}
- Total word count: ${metadata.wordCount}
- Estimated total reading time: ${metadata.readingTime} minute(s)

Current chunk metadata:
- Chunk character count: ${chunkMetadata.characterCount}
- Chunk word count: ${chunkMetadata.wordCount}

${buildAnalysisInstructions(promptMode)}

Chunk transcript text:
The transcript text below is cleaned for readability. A timestamped transcript is also available separately in the app.

${chunkText}
`;
}
