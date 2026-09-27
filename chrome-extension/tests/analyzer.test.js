// Mirrors tests_manual.py so the extension's logic stays in step with app.py.
// Run with: npm test (or node --test tests/*.test.js)

import assert from "node:assert/strict";
import test from "node:test";

import {
  CHUNK_WORD_LIMIT,
  buildAnalysisInstructions,
  buildChatgptAnalysisPrompt,
  buildChunkedChatgptPrompt,
  buildTimestampedTranscript,
  calculateTranscriptMetadata,
  cleanTranscriptText,
  extractVideoId,
  formatTimestamp,
  slugifyPromptMode,
  splitTranscriptIntoChunks,
} from "../lib/analyzer.js";

test("extractVideoId", () => {
  const expectedVideoId = "dQw4w9WgXcQ";
  const validInputs = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "dQw4w9WgXcQ",
    "youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
  ];

  for (const videoInput of validInputs) {
    assert.equal(extractVideoId(videoInput), expectedVideoId, videoInput);
  }

  const invalidInputs = [
    "",
    "hello",
    "https://evilyoutube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=bad",
  ];

  for (const videoInput of invalidInputs) {
    assert.equal(extractVideoId(videoInput), null, videoInput);
  }
});

test("slugifyPromptMode", () => {
  assert.equal(slugifyPromptMode("General Analysis"), "general_analysis");
  assert.equal(slugifyPromptMode("Study Notes"), "study_notes");
  assert.equal(slugifyPromptMode("Technical / Engineering Review"), "technical_engineering_review");
  assert.equal(slugifyPromptMode("Action Plan"), "action_plan");
});

test("calculateTranscriptMetadata", () => {
  const transcriptText = "One two three.";
  const metadata = calculateTranscriptMetadata(transcriptText);

  assert.equal(metadata.characterCount, transcriptText.length);
  assert.equal(metadata.wordCount, 3);
  assert.ok(metadata.readingTime >= 1);
});

test("calculateTranscriptMetadata rounds reading time like Python", () => {
  // Python's round() sends halfway values to the nearest even number.
  assert.equal(calculateTranscriptMetadata(Array(500).fill("w").join(" ")).readingTime, 2);
  assert.equal(calculateTranscriptMetadata(Array(300).fill("w").join(" ")).readingTime, 2);
  assert.equal(calculateTranscriptMetadata("").readingTime, 1);
});

test("splitTranscriptIntoChunks", () => {
  const words = Array(CHUNK_WORD_LIMIT + 25).fill("word");
  const chunks = splitTranscriptIntoChunks(words.join(" "));

  assert.ok(chunks.length > 1);

  const chunkWordCounts = chunks.map((chunk) => chunk.split(" ").length);

  for (const chunkWordCount of chunkWordCounts) {
    assert.ok(chunkWordCount <= CHUNK_WORD_LIMIT);
  }

  assert.equal(
    chunkWordCounts.reduce((total, count) => total + count, 0),
    words.length,
  );
});

test("formatTimestamp", () => {
  assert.equal(formatTimestamp(0), "00:00");
  assert.equal(formatTimestamp(65.2), "01:05");
  assert.equal(formatTimestamp(3723), "01:02:03");
});

test("buildTimestampedTranscript", () => {
  const segments = [
    { start: 0, text: "First transcript line." },
    { start: 4.2, text: "Next transcript line." },
  ];
  const timestampedTranscript = buildTimestampedTranscript(segments);

  assert.ok(timestampedTranscript.includes("[00:00] First transcript line."));
  assert.ok(timestampedTranscript.includes("[00:04] Next transcript line."));
});

test("cleanTranscriptText groups sentences into paragraphs", () => {
  const sentence = "This sentence is exactly long enough to help build a paragraph.";
  const segments = Array.from({ length: 12 }, () => ({ text: `  ${sentence}\n` }));
  const paragraphs = cleanTranscriptText(segments).split("\n\n");

  assert.ok(paragraphs.length > 1);
  assert.ok(paragraphs[0].length >= 500);
  assert.ok(!/\s{2,}/.test(paragraphs.join(" ")));
});

test("buildChatgptAnalysisPrompt includes title", () => {
  const metadata = { characterCount: 100, wordCount: 20, readingTime: 1 };
  const prompt = buildChatgptAnalysisPrompt(
    "dQw4w9WgXcQ",
    metadata,
    "Readable transcript text.",
    "General Analysis",
    "Example Video Title",
  );

  assert.ok(prompt.includes("Video title: Example Video Title"));
});

test("buildChunkedChatgptPrompt", () => {
  const fullMetadata = { characterCount: 1000, wordCount: 200, readingTime: 1 };
  const chunkText = "This is the chunk text.";
  const promptMode = "Study Notes";
  const prompt = buildChunkedChatgptPrompt(
    "dQw4w9WgXcQ",
    fullMetadata,
    chunkText,
    1,
    3,
    promptMode,
    "Example Video Title",
  );

  assert.ok(prompt.includes("Video title: Example Video Title"));
  assert.ok(prompt.includes("Whole transcript metadata"));
  assert.ok(prompt.includes("Current chunk metadata"));
  assert.ok(prompt.includes("Chunk: 1 of 3"));
  assert.ok(prompt.includes(buildAnalysisInstructions(promptMode)));
  assert.ok(prompt.includes(chunkText));
});
