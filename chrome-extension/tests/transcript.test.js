import assert from "node:assert/strict";
import test from "node:test";

import {
  ERROR_CODES,
  TranscriptError,
  fetchTranscript,
  findEnglishTrack,
  getTranscriptErrorMessage,
  parseTranscriptXml,
} from "../lib/transcript.js";

const WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "test_key-123"});</script>';
const CAPTION_XML = `<?xml version="1.0" encoding="utf-8" ?><transcript>
<text start="0.5" dur="2.1">Hello &amp;amp; welcome</text>
<text start="2.6" dur="3">It&amp;#39;s &lt;i&gt;great&lt;/i&gt; to be here</text>
<text start="5.6" dur="1"></text>
</transcript>`;

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), { status });
}

function playerData(overrides = {}) {
  return {
    playabilityStatus: { status: "OK" },
    videoDetails: { title: "Sample Title" },
    captions: {
      playerCaptionsTracklistRenderer: {
        captionTracks: [
          { baseUrl: "https://www.youtube.com/api/timedtext?v=x&lang=en&fmt=srv3", languageCode: "en", kind: "asr" },
        ],
      },
    },
    ...overrides,
  };
}

function mockFetch({ watch = WATCH_HTML, player = playerData(), captions = CAPTION_XML } = {}) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });

    if (url.startsWith("https://www.youtube.com/watch")) {
      return watch instanceof Response ? watch : new Response(watch);
    }

    if (url.startsWith("https://www.youtube.com/youtubei/v1/player")) {
      return player instanceof Response ? player : jsonResponse(player);
    }

    return captions instanceof Response ? captions : new Response(captions);
  };

  return { calls, fetchImpl };
}

async function assertTranscriptError(promise, code) {
  await assert.rejects(promise, (error) => error instanceof TranscriptError && error.code === code);
}

test("parseTranscriptXml decodes double-escaped text and strips tags", () => {
  const segments = parseTranscriptXml(CAPTION_XML);

  assert.deepEqual(segments, [
    { text: "Hello & welcome", start: 0.5, duration: 2.1 },
    { text: "It's great to be here", start: 2.6, duration: 3 },
  ]);
});

test("parseTranscriptXml rejects non-transcript responses", () => {
  assert.throws(() => parseTranscriptXml(""), (error) => error.code === ERROR_CODES.DATA_UNPARSABLE);
});

test("findEnglishTrack prefers manual captions, then exact language matches", () => {
  const generatedEn = { languageCode: "en", kind: "asr" };
  const manualEnGb = { languageCode: "en-GB" };
  const manualEn = { languageCode: "en" };
  const french = { languageCode: "fr" };

  assert.equal(findEnglishTrack([generatedEn, manualEn, french]), manualEn);
  assert.equal(findEnglishTrack([manualEnGb, generatedEn]), generatedEn);
  assert.equal(findEnglishTrack([manualEnGb, french]), manualEnGb);
  assert.equal(findEnglishTrack([french]), null);
});

test("fetchTranscript runs the watch page, Innertube, and caption requests", async () => {
  const { calls, fetchImpl } = mockFetch();
  const result = await fetchTranscript("dQw4w9WgXcQ", fetchImpl);

  assert.equal(result.title, "Sample Title");
  assert.equal(result.languageCode, "en");
  assert.equal(result.isGenerated, true);
  assert.equal(result.segments.length, 2);

  assert.equal(calls[0].url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  assert.equal(calls[1].url, "https://www.youtube.com/youtubei/v1/player?key=test_key-123");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    context: { client: { clientName: "ANDROID", clientVersion: "20.10.38" } },
    videoId: "dQw4w9WgXcQ",
  });
  assert.equal(calls[2].url, "https://www.youtube.com/api/timedtext?v=x&lang=en");
});

test("fetchTranscript maps YouTube failures to transcript errors", async () => {
  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", mockFetch({ player: playerData({ captions: undefined }) }).fetchImpl),
    ERROR_CODES.TRANSCRIPTS_DISABLED,
  );

  const frenchOnly = playerData({
    captions: { playerCaptionsTracklistRenderer: { captionTracks: [{ baseUrl: "https://x", languageCode: "fr" }] } },
  });
  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", mockFetch({ player: frenchOnly }).fetchImpl),
    ERROR_CODES.NO_TRANSCRIPT_FOUND,
  );

  const unavailable = playerData({ playabilityStatus: { status: "ERROR", reason: "This video is unavailable" } });
  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", mockFetch({ player: unavailable }).fetchImpl),
    ERROR_CODES.VIDEO_UNAVAILABLE,
  );

  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", mockFetch({ watch: new Response("", { status: 429 }) }).fetchImpl),
    ERROR_CODES.IP_BLOCKED,
  );

  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", mockFetch({ watch: '<form action="https://consent.youtube.com/s">' }).fetchImpl),
    ERROR_CODES.CONSENT_REQUIRED,
  );

  await assertTranscriptError(
    fetchTranscript("dQw4w9WgXcQ", async () => {
      throw new TypeError("Failed to fetch");
    }),
    ERROR_CODES.REQUEST_FAILED,
  );
});

test("getTranscriptErrorMessage matches app.py wording", () => {
  assert.equal(
    getTranscriptErrorMessage(new TranscriptError(ERROR_CODES.TRANSCRIPTS_DISABLED)),
    "Transcript disabled: this video does not allow transcript access.",
  );
  assert.equal(
    getTranscriptErrorMessage(new TranscriptError(ERROR_CODES.NO_TRANSCRIPT_FOUND)),
    "No English transcript found for this video.",
  );
  assert.equal(
    getTranscriptErrorMessage(new TranscriptError(ERROR_CODES.REQUEST_BLOCKED)),
    "Network or YouTube request failure: please check your connection and try again.",
  );
  assert.equal(getTranscriptErrorMessage(new Error("boom")), "Unknown transcript error: boom");
});
