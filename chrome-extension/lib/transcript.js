// Fetches YouTube transcripts the same way youtube-transcript-api (used by app.py) does:
// 1. Load the watch page to read the public Innertube API key.
// 2. Ask the Innertube player endpoint (as the Android client) for the caption tracks.
// 3. Download the English caption track and parse its XML into timed segments.

const WATCH_URL = "https://www.youtube.com/watch?v=";
const INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/player?key=";
const INNERTUBE_CONTEXT = { client: { clientName: "ANDROID", clientVersion: "20.10.38" } };
const CONSENT_FORM_MARKER = 'action="https://consent.youtube.com/s"';
const BOT_DETECTED_REASON = "Sign in to confirm you’re not a bot";
const AGE_RESTRICTED_REASON = "This video may be inappropriate for some users.";
const VIDEO_UNAVAILABLE_REASON = "This video is unavailable";

export const ERROR_CODES = {
  TRANSCRIPTS_DISABLED: "TRANSCRIPTS_DISABLED",
  NO_TRANSCRIPT_FOUND: "NO_TRANSCRIPT_FOUND",
  VIDEO_UNAVAILABLE: "VIDEO_UNAVAILABLE",
  REQUEST_FAILED: "REQUEST_FAILED",
  REQUEST_BLOCKED: "REQUEST_BLOCKED",
  IP_BLOCKED: "IP_BLOCKED",
  CONSENT_REQUIRED: "CONSENT_REQUIRED",
  AGE_RESTRICTED: "AGE_RESTRICTED",
  VIDEO_UNPLAYABLE: "VIDEO_UNPLAYABLE",
  PO_TOKEN_REQUIRED: "PO_TOKEN_REQUIRED",
  DATA_UNPARSABLE: "DATA_UNPARSABLE",
};

export class TranscriptError extends Error {
  constructor(code, detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.name = "TranscriptError";
    this.code = code;
  }
}

/** Convert transcript errors into the same user-facing messages app.py shows. */
export function getTranscriptErrorMessage(error) {
  switch (error?.code) {
    case ERROR_CODES.TRANSCRIPTS_DISABLED:
      return "Transcript disabled: this video does not allow transcript access.";
    case ERROR_CODES.NO_TRANSCRIPT_FOUND:
      return "No English transcript found for this video.";
    case ERROR_CODES.VIDEO_UNAVAILABLE:
      return "Transcript unavailable: this video is unavailable or cannot be accessed.";
    case ERROR_CODES.REQUEST_FAILED:
    case ERROR_CODES.REQUEST_BLOCKED:
    case ERROR_CODES.IP_BLOCKED:
      return "Network or YouTube request failure: please check your connection and try again.";
    case ERROR_CODES.CONSENT_REQUIRED:
      return "YouTube is asking for cookie consent. Open youtube.com in this browser, answer the consent prompt, then try again.";
    case ERROR_CODES.AGE_RESTRICTED:
    case ERROR_CODES.VIDEO_UNPLAYABLE:
    case ERROR_CODES.PO_TOKEN_REQUIRED:
    case ERROR_CODES.DATA_UNPARSABLE:
      return "Transcript unavailable: YouTube did not return a usable transcript for this video.";
    default:
      return `Unknown transcript error: ${error?.message || error}`;
  }
}

async function request(fetchImpl, url, options) {
  let response;

  try {
    response = await fetchImpl(url, options);
  } catch (error) {
    throw new TranscriptError(ERROR_CODES.REQUEST_FAILED, error.message);
  }

  if (response.status === 429) {
    throw new TranscriptError(ERROR_CODES.IP_BLOCKED);
  }

  if (!response.ok) {
    throw new TranscriptError(ERROR_CODES.REQUEST_FAILED, `HTTP ${response.status}`);
  }

  return response;
}

function extractInnertubeApiKey(html) {
  const match = html.match(/"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"/);

  if (match) {
    return match[1];
  }

  if (html.includes(CONSENT_FORM_MARKER)) {
    throw new TranscriptError(ERROR_CODES.CONSENT_REQUIRED);
  }

  if (html.includes('class="g-recaptcha"')) {
    throw new TranscriptError(ERROR_CODES.IP_BLOCKED);
  }

  throw new TranscriptError(ERROR_CODES.DATA_UNPARSABLE, "Innertube API key not found");
}

function assertPlayability(playabilityStatus = {}) {
  const { status, reason } = playabilityStatus;

  if (status == null || status === "OK") {
    return;
  }

  if (status === "LOGIN_REQUIRED" && reason === BOT_DETECTED_REASON) {
    throw new TranscriptError(ERROR_CODES.REQUEST_BLOCKED);
  }

  if (status === "LOGIN_REQUIRED" && reason === AGE_RESTRICTED_REASON) {
    throw new TranscriptError(ERROR_CODES.AGE_RESTRICTED);
  }

  if (status === "ERROR" && reason === VIDEO_UNAVAILABLE_REASON) {
    throw new TranscriptError(ERROR_CODES.VIDEO_UNAVAILABLE);
  }

  throw new TranscriptError(ERROR_CODES.VIDEO_UNPLAYABLE, reason || status);
}

/**
 * Pick an English caption track. Manually created captions win over
 * auto-generated ones, and an exact "en" match wins over regional variants.
 */
export function findEnglishTrack(captionTracks) {
  const manualTracks = captionTracks.filter((track) => track.kind !== "asr");
  const generatedTracks = captionTracks.filter((track) => track.kind === "asr");
  const matchers = [
    (track) => track.languageCode === "en",
    (track) => /^en-/i.test(track.languageCode || ""),
  ];

  for (const matches of matchers) {
    for (const tracks of [manualTracks, generatedTracks]) {
      const track = tracks.find(matches);

      if (track) {
        return track;
      }
    }
  }

  return null;
}

const NAMED_ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };

function decodeEntities(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, name) => {
    if (name[0] === "#") {
      const isHex = name[1] === "x" || name[1] === "X";
      const codePoint = parseInt(name.slice(isHex ? 2 : 1), isHex ? 16 : 10);

      return Number.isFinite(codePoint) && codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : entity;
    }

    return NAMED_ENTITIES[name.toLowerCase()] ?? entity;
  });
}

/**
 * Parse YouTube's timed-text XML into { text, start, duration } segments.
 * Caption text is escaped twice (XML, then HTML), so it is decoded twice and
 * any leftover formatting tags are stripped.
 */
export function parseTranscriptXml(xml) {
  const segments = [];
  const textElementPattern = /<text\b([^>]*?)(?:\/>|>([\s\S]*?)<\/text>)/g;

  for (const [, attributes, rawText] of xml.matchAll(textElementPattern)) {
    if (rawText === undefined || rawText === "") {
      continue;
    }

    const start = attributes.match(/\bstart="([^"]*)"/);
    const duration = attributes.match(/\bdur="([^"]*)"/);

    segments.push({
      text: decodeEntities(decodeEntities(rawText)).replace(/<[^>]*>/g, ""),
      start: start ? parseFloat(start[1]) : 0,
      duration: duration ? parseFloat(duration[1]) : 0,
    });
  }

  if (!segments.length && !/<transcript\b/.test(xml)) {
    throw new TranscriptError(ERROR_CODES.DATA_UNPARSABLE, "Caption track is not timed-text XML");
  }

  return segments;
}

/**
 * Fetch the video title and English transcript segments for a video ID.
 * `fetchImpl` can be swapped out in tests.
 */
export async function fetchTranscript(videoId, fetchImpl = globalThis.fetch.bind(globalThis)) {
  // Send the browser's own YouTube cookies here so an answered consent prompt
  // (common in the EU) is respected instead of returning the consent page.
  const watchResponse = await request(fetchImpl, WATCH_URL + encodeURIComponent(videoId), {
    credentials: "include",
    headers: { "Accept-Language": "en-US" },
  });
  const apiKey = extractInnertubeApiKey(await watchResponse.text());

  const playerResponse = await request(fetchImpl, INNERTUBE_API_URL + apiKey, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json", "Accept-Language": "en-US" },
    body: JSON.stringify({ context: INNERTUBE_CONTEXT, videoId }),
  });

  let playerData;

  try {
    playerData = await playerResponse.json();
  } catch (error) {
    throw new TranscriptError(ERROR_CODES.DATA_UNPARSABLE, error.message);
  }

  assertPlayability(playerData.playabilityStatus);

  const captionTracks = playerData.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!captionTracks) {
    throw new TranscriptError(ERROR_CODES.TRANSCRIPTS_DISABLED);
  }

  const track = findEnglishTrack(captionTracks);

  if (!track) {
    throw new TranscriptError(ERROR_CODES.NO_TRANSCRIPT_FOUND);
  }

  const trackUrl = track.baseUrl.replace("&fmt=srv3", "");

  if (trackUrl.includes("&exp=xpe")) {
    throw new TranscriptError(ERROR_CODES.PO_TOKEN_REQUIRED);
  }

  const trackResponse = await request(fetchImpl, trackUrl, { credentials: "omit" });

  return {
    title: playerData.videoDetails?.title || "Unknown title",
    languageCode: track.languageCode,
    isGenerated: track.kind === "asr",
    segments: parseTranscriptXml(await trackResponse.text()),
  };
}
