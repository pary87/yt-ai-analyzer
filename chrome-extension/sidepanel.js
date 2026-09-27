import {
  LONG_TRANSCRIPT_WORD_LIMIT,
  PROMPT_MODES,
  buildChatgptAnalysisPrompt,
  buildChunkedChatgptPrompt,
  buildTimestampedTranscript,
  calculateTranscriptMetadata,
  cleanTranscriptText,
  extractVideoId,
  slugifyPromptMode,
  splitTranscriptIntoChunks,
} from "./lib/analyzer.js";
import { fetchTranscript, getTranscriptErrorMessage } from "./lib/transcript.js";

const elements = {
  form: document.getElementById("analyze-form"),
  urlInput: document.getElementById("youtube-url"),
  useCurrentTab: document.getElementById("use-current-tab"),
  promptMode: document.getElementById("prompt-mode"),
  analyzeButton: document.getElementById("analyze-button"),
  status: document.getElementById("status"),
  error: document.getElementById("error"),
  results: document.getElementById("results"),
  videoTitle: document.getElementById("video-title"),
  videoId: document.getElementById("video-id"),
  wordCount: document.getElementById("word-count"),
  characterCount: document.getElementById("character-count"),
  readingTime: document.getElementById("reading-time"),
  trackInfo: document.getElementById("track-info"),
  longWarning: document.getElementById("long-warning"),
  transcriptPreview: document.getElementById("transcript-preview"),
  fullTranscript: document.getElementById("full-transcript"),
  timestampedTranscript: document.getElementById("timestamped-transcript"),
  chatgptPrompt: document.getElementById("chatgpt-prompt"),
  chunkSection: document.getElementById("chunk-section"),
  chunkList: document.getElementById("chunk-list"),
  chunkTemplate: document.getElementById("chunk-template"),
  debug: document.getElementById("debug"),
  debugList: document.getElementById("debug-list"),
};

// Transcripts fetched during this session, keyed by video ID, so switching
// prompt modes or re-analyzing the same video does not hit YouTube again.
const transcriptCache = new Map();
let currentResult = null;
let urlWasAutoFilled = false;

for (const mode of PROMPT_MODES) {
  elements.promptMode.append(new Option(mode, mode));
}

function updateAnalyzeButton() {
  elements.analyzeButton.disabled = !elements.urlInput.value.trim();
}

function setUrl(url, autoFilled) {
  elements.urlInput.value = url;
  urlWasAutoFilled = autoFilled;
  updateAnalyzeButton();
}

async function getActiveTabVideoUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

  // tab.url is only visible for YouTube tabs (the extension's host permission).
  return tab?.url && extractVideoId(tab.url) ? tab.url : null;
}

async function fillFromActiveTab({ onlyIfAutoFilled }) {
  if (onlyIfAutoFilled && elements.urlInput.value.trim() && !urlWasAutoFilled) {
    return;
  }

  const tabUrl = await getActiveTabVideoUrl();

  if (tabUrl) {
    setUrl(tabUrl, true);
  }
}

function downloadText(fileName, text) {
  const objectUrl = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");

  link.href = objectUrl;
  link.download = fileName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function copyText(button, text) {
  // Remember the real label so a second click during "Copied!" can't overwrite it.
  button.dataset.label ??= button.textContent;
  clearTimeout(Number(button.dataset.resetTimer));

  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied!";
  } catch {
    button.textContent = "Copy failed";
  }

  button.dataset.resetTimer = setTimeout(() => {
    button.textContent = button.dataset.label;
  }, 1500);
}

function showDebugInfo(entries) {
  elements.debugList.replaceChildren();

  for (const [label, value] of entries) {
    const term = document.createElement("dt");
    const detail = document.createElement("dd");

    term.textContent = label;
    detail.textContent = String(value);
    elements.debugList.append(term, detail);
  }

  elements.debug.hidden = false;
}

function buildPrompts(result, promptMode) {
  const { videoId, title, metadata, transcriptText } = result;
  const promptModeSlug = slugifyPromptMode(promptMode);
  const prompt = {
    text: buildChatgptAnalysisPrompt(videoId, metadata, transcriptText, promptMode, title),
    fileName: `chatgpt_prompt_${videoId}_${promptModeSlug}_full.txt`,
  };
  const chunks = [];

  if (metadata.wordCount > LONG_TRANSCRIPT_WORD_LIMIT) {
    const transcriptChunks = splitTranscriptIntoChunks(transcriptText);
    const totalChunks = transcriptChunks.length;

    transcriptChunks.forEach((chunkText, index) => {
      const chunkNumber = index + 1;

      chunks.push({
        chunkNumber,
        totalChunks,
        text: buildChunkedChatgptPrompt(videoId, metadata, chunkText, chunkNumber, totalChunks, promptMode, title),
        fileName: `chatgpt_prompt_${videoId}_${promptModeSlug}_part_${chunkNumber}_of_${totalChunks}.txt`,
      });
    });
  }

  return { prompt, chunks };
}

function renderPrompts() {
  const { prompt, chunks } = buildPrompts(currentResult, elements.promptMode.value);

  currentResult.prompt = prompt;
  elements.chatgptPrompt.value = prompt.text;
  elements.chunkList.replaceChildren();
  elements.chunkSection.hidden = chunks.length === 0;

  for (const chunk of chunks) {
    const chunkElement = elements.chunkTemplate.content.firstElementChild.cloneNode(true);
    const downloadButton = chunkElement.querySelector("[data-chunk-download]");

    chunkElement.querySelector("summary").textContent = `Chunk ${chunk.chunkNumber} of ${chunk.totalChunks}`;
    chunkElement.querySelector("textarea").value = chunk.text;
    chunkElement.querySelector("textarea").setAttribute("aria-label", `ChatGPT prompt part ${chunk.chunkNumber}`);
    chunkElement.querySelector("[data-chunk-copy]").setAttribute("aria-label", `Copy prompt part ${chunk.chunkNumber}`);
    chunkElement.querySelector("[data-chunk-copy]").addEventListener("click", (event) => {
      copyText(event.currentTarget, chunk.text);
    });
    downloadButton.title = `Download ChatGPT Prompt Part ${chunk.chunkNumber}`;
    downloadButton.setAttribute("aria-label", downloadButton.title);
    downloadButton.addEventListener("click", () => downloadText(chunk.fileName, chunk.text));
    elements.chunkList.append(chunkElement);
  }
}

function renderResult() {
  const { videoId, title, metadata, transcriptText, timestampedTranscript, languageCode, isGenerated } = currentResult;

  elements.videoTitle.textContent = title;
  elements.videoId.textContent = videoId;
  elements.wordCount.textContent = metadata.wordCount.toLocaleString();
  elements.characterCount.textContent = metadata.characterCount.toLocaleString();
  elements.readingTime.textContent = `${metadata.readingTime} minute(s)`;
  elements.trackInfo.textContent = `Caption track: ${languageCode} (${isGenerated ? "auto-generated" : "manually created"})`;
  elements.longWarning.hidden = metadata.wordCount <= LONG_TRANSCRIPT_WORD_LIMIT;
  elements.transcriptPreview.textContent = transcriptText.slice(0, 1000);
  elements.fullTranscript.textContent = transcriptText;
  elements.timestampedTranscript.textContent = timestampedTranscript;
  renderPrompts();
  elements.results.hidden = false;
}

async function analyze() {
  const youtubeUrl = elements.urlInput.value;
  const videoId = extractVideoId(youtubeUrl);

  currentResult = null;
  elements.results.hidden = true;
  elements.error.hidden = true;

  if (!videoId) {
    elements.error.textContent =
      "Invalid YouTube URL or video ID. Please paste a supported YouTube URL or an 11-character video ID.";
    elements.error.hidden = false;
    showDebugInfo([
      ["Raw extracted video ID", videoId],
      ["Input URL", youtubeUrl],
    ]);
    return;
  }

  elements.status.hidden = false;
  elements.analyzeButton.disabled = true;

  try {
    if (!transcriptCache.has(videoId)) {
      transcriptCache.set(videoId, await fetchTranscript(videoId));
    }

    const { title, segments, languageCode, isGenerated } = transcriptCache.get(videoId);
    const transcriptText = cleanTranscriptText(segments);

    currentResult = {
      videoId,
      title,
      languageCode,
      isGenerated,
      transcriptText,
      timestampedTranscript: buildTimestampedTranscript(segments),
      metadata: calculateTranscriptMetadata(transcriptText),
    };
    renderResult();
    showDebugInfo([
      ["Raw extracted video ID", videoId],
      ["Input URL", youtubeUrl],
      ["Transcript segment count", segments.length],
    ]);
  } catch (error) {
    console.error(error);
    elements.error.textContent = getTranscriptErrorMessage(error);
    elements.error.hidden = false;
    showDebugInfo([
      ["Raw extracted video ID", videoId],
      ["Input URL", youtubeUrl],
      ["Error", error.message || error],
    ]);
  } finally {
    elements.status.hidden = true;
    updateAnalyzeButton();
  }
}

elements.urlInput.addEventListener("input", () => {
  urlWasAutoFilled = false;
  updateAnalyzeButton();
});

elements.useCurrentTab.addEventListener("click", async () => {
  const tabUrl = await getActiveTabVideoUrl();

  if (tabUrl) {
    setUrl(tabUrl, true);
    elements.error.hidden = true;
  } else {
    elements.error.textContent = "The current tab is not a YouTube video. Open a video on youtube.com or paste a URL.";
    elements.error.hidden = false;
  }
});

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  analyze();
});

elements.promptMode.addEventListener("change", () => {
  if (currentResult) {
    renderPrompts();
  }
});

document.addEventListener("click", (event) => {
  const copyTarget = event.target.closest("[data-copy]");
  const downloadTarget = event.target.closest("[data-download]");

  if (!currentResult || (!copyTarget && !downloadTarget)) {
    return;
  }

  const { videoId, transcriptText, timestampedTranscript, prompt } = currentResult;
  const outputs = {
    readable: { text: transcriptText, fileName: `transcript_${videoId}_readable.txt` },
    timestamped: { text: timestampedTranscript, fileName: `transcript_${videoId}_timestamped.txt` },
    prompt,
  };

  if (copyTarget) {
    copyText(copyTarget, outputs[copyTarget.dataset.copy].text);
  } else {
    const { fileName, text } = outputs[downloadTarget.dataset.download];
    downloadText(fileName, text);
  }
});

// Keep the URL field in step with the video in the current tab, unless the
// user has typed their own URL.
chrome.tabs.onActivated.addListener(() => fillFromActiveTab({ onlyIfAutoFilled: true }));
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && tab.active) {
    fillFromActiveTab({ onlyIfAutoFilled: true });
  }
});

fillFromActiveTab({ onlyIfAutoFilled: false });
updateAnalyzeButton();
