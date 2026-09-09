"use strict";

/* The page. Vanilla JS, no build step.
 *
 * Domain rules are not duplicated here — bounds and caption edits go to the
 * server, which enforces the invariants and returns either the updated clip or
 * a message. Re-implementing the 15-60s rule in the browser would give it two
 * homes and one of them would drift. */

const el = (id) => document.getElementById(id);

const views = {
  landing: el("view-landing"),
  processing: el("view-processing"),
  results: el("view-results"),
  editor: el("view-editor"),
};

/* Stage order and labels mirror clipping/core/progress.py. The page shows what
 * the backend is actually doing, so this list must match its stage keys. */
const STAGES = [
  ["model-download", "Downloading model"],
  ["audio-fetch", "Downloading audio"],
  ["survey", "Transcribing"],
  ["hook", "Scoring"],
  ["precise", "Timing words"],
  ["video-fetch", "Downloading video"],
  ["captions", "Building captions"],
  ["render", "Rendering"],
];

const CONTEXT_SECONDS = 30;

let clips = [];
let current = null;      // the clip being edited
let view = { min: 0, max: 0 };
let polling = null;
let seenStages = new Set();

function show(name) {
  for (const [key, node] of Object.entries(views)) node.hidden = key !== name;
}

function formatTimecode(seconds) {
  const safe = Math.max(seconds, 0);
  const minutes = Math.floor(safe / 60);
  const rest = (safe % 60).toFixed(1).padStart(4, "0");
  return `${minutes}:${rest}`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `request failed (${response.status})`);
  return body;
}

/* --- Landing ------------------------------------------------------------- */

el("import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = el("url").value.trim();
  if (!url) return fieldError("Paste a YouTube link first.");
  clearFieldError();

  const count = Math.min(Math.max(Number(el("clip-count").value) || 3, 1), 5);
  seenStages = new Set();
  renderStages(null);
  show("processing");

  try {
    await api("/api/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, clips: count }),
    });
    startPolling();
  } catch (error) {
    show("landing");
    fieldError(error.message);
  }
});

function fieldError(message) {
  el("url-error").textContent = message;
  el("url-error").hidden = false;
  el("url").setAttribute("aria-invalid", "true");
}

function clearFieldError() {
  el("url-error").hidden = true;
  el("url").removeAttribute("aria-invalid");
}

el("start-over").addEventListener("click", () => {
  el("url").value = "";
  show("landing");
});

el("back").addEventListener("click", () => show("results"));

/* --- Progress ------------------------------------------------------------ */

function startPolling() {
  if (polling) clearInterval(polling);
  /* 400ms: fast enough that the percentage looks continuous during a long
   * transcription, slow enough to be free on localhost. */
  polling = setInterval(refresh, 400);
  refresh();
}

async function refresh() {
  let state;
  try {
    state = await api("/api/status");
  } catch (error) {
    return runError(error.message);
  }

  renderProgress(state);

  if (state.phase === "failed") {
    clearInterval(polling);
    polling = null;
    return runError(state.error || "the run failed");
  }

  if (state.busy) return;

  clearInterval(polling);
  polling = null;

  if (state.clips && state.clips.length) {
    clips = state.clips;
    if (state.phase === "exported" && current) {
      const path = state.exports?.[String(current.index)];
      el("export-note").textContent = path ? `Saved to ${path}` : "Exported.";
      el("export").disabled = false;
      return show("editor");
    }
    renderResults(state);
    show("results");
  }
}

function renderProgress(state) {
  const percent = state.overall_percent ?? 0;
  el("percent").textContent = `${Math.round(percent)}%`;
  el("phase").textContent = state.label || "Working";
  el("phase-detail").textContent = state.detail || "";

  const bar = el("bar");
  bar.dataset.determinate = String(state.determinate !== false);
  bar.setAttribute("aria-valuenow", String(Math.round(percent)));
  el("bar-fill").style.width = `${percent}%`;

  if (state.stage) seenStages.add(state.stage);
  renderStages(state.stage);
}

function renderStages(activeStage) {
  const list = el("stages");
  list.innerHTML = "";
  for (const [key, label] of STAGES) {
    /* The model download only appears once it actually happens — on a warm
     * cache it never runs, and listing it would promise work that never comes. */
    if (key === "model-download" && !seenStages.has(key)) continue;

    const item = document.createElement("li");
    item.textContent = label;
    if (key === activeStage) item.dataset.state = "active";
    else if (seenStages.has(key)) item.dataset.state = "done";
    else item.dataset.state = "pending";
    list.appendChild(item);
  }
}

function runError(message) {
  const node = el("run-error");
  node.textContent = message;
  node.hidden = false;
  show("processing");
}

/* --- Results ------------------------------------------------------------- */

function renderResults(state) {
  const timings = state.timings || [];
  const total = timings.reduce((sum, t) => sum + t.seconds, 0);
  el("results-sub").textContent =
    `${clips.length} clip${clips.length === 1 ? "" : "s"} in ${total.toFixed(0)}s`;

  const grid = el("grid");
  grid.innerHTML = "";

  for (const clip of clips) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "clip-card";
    card.setAttribute("aria-label", `Clip ${clip.rank}, ${clip.duration.toFixed(0)} seconds`);

    const thumb = document.createElement("div");
    thumb.className = "clip-thumb";
    const video = document.createElement("video");
    video.src = `/api/video/${clip.index}`;
    video.muted = true;
    video.preload = "metadata";
    video.addEventListener("mouseenter", () => video.play().catch(() => {}));
    video.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = `#${clip.rank}`;
    thumb.append(video, rank);

    const body = document.createElement("div");
    body.className = "clip-body";

    const meta = document.createElement("div");
    meta.className = "clip-meta";
    const duration = document.createElement("span");
    duration.textContent = `${clip.duration.toFixed(1)}s`;
    const at = document.createElement("span");
    at.textContent = formatTimecode(clip.start);
    meta.append(duration, at);
    if (clip.score) {
      const score = document.createElement("span");
      score.textContent = `score ${clip.score.toFixed(2)}`;
      meta.append(score);
    }

    const reason = document.createElement("p");
    reason.className = "clip-reason";
    reason.textContent = clip.reason;

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.dataset.origin = clip.origin;
    badge.textContent = clip.origin === "heuristic" ? "Heuristic fallback" : "Model pick";

    body.append(meta, reason, badge);
    if (clip.truncated) {
      const note = document.createElement("p");
      note.className = "clip-reason";
      note.textContent = "Span exceeded 60s and was truncated.";
      body.append(note);
    }

    card.append(thumb, body);
    card.addEventListener("click", () => openEditor(clip));
    grid.appendChild(card);
  }
}

/* --- Editor -------------------------------------------------------------- */

function openEditor(clip) {
  current = clip;
  view = {
    min: Math.max(clip.start - CONTEXT_SECONDS, 0),
    max: clip.end + CONTEXT_SECONDS,
  };
  el("editor-title").textContent = `Clip #${clip.rank}`;
  el("preview").src = `/api/video/${clip.index}`;
  el("export-note").textContent = "";
  el("export").disabled = false;
  renderTimeline();
  renderCaptions();
  show("editor");
}

const positionFor = (seconds) =>
  ((seconds - view.min) / (view.max - view.min || 1)) * 100;
const secondsFor = (ratio) => view.min + ratio * (view.max - view.min);

function renderTimeline() {
  const left = positionFor(current.start);
  const right = positionFor(current.end);
  el("span").style.left = `${left}%`;
  el("span").style.width = `${Math.max(right - left, 0)}%`;

  /* Each handle is a 44px hit area centred on the boundary it controls. */
  el("handle-start").style.left = `calc(${left}% - (var(--handle-width) / 2))`;
  el("handle-end").style.left = `calc(${right}% - (var(--handle-width) / 2))`;

  el("tc-start").textContent = formatTimecode(current.start);
  el("tc-end").textContent = formatTimecode(current.end);
  el("tc-length").textContent = `${current.duration.toFixed(1)}s`;

  for (const [node, value] of [
    [el("handle-start"), current.start],
    [el("handle-end"), current.end],
  ]) {
    node.setAttribute("aria-valuemin", view.min.toFixed(1));
    node.setAttribute("aria-valuemax", view.max.toFixed(1));
    node.setAttribute("aria-valuenow", value.toFixed(1));
    node.setAttribute("aria-valuetext", formatTimecode(value));
  }
}

async function commitBounds(start, end) {
  try {
    const body = await api("/api/bounds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_index: current.index, start, end }),
    });
    el("timeline").dataset.invalid = "false";
    el("timeline-message").textContent = "";
    current = body.clip;
    clips[current.index] = current;
    renderTimeline();
    renderCaptions();
  } catch (error) {
    /* The server refused it, so the visual state rolls back to the last
     * accepted clip rather than showing something that was rejected. */
    el("timeline").dataset.invalid = "true";
    el("timeline-message").textContent = error.message;
    renderTimeline();
  }
}

for (const [node, edge] of [[el("handle-start"), "start"], [el("handle-end"), "end"]]) {
  node.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    node.setPointerCapture(event.pointerId);

    const onMove = (move) => {
      const rect = el("timeline").getBoundingClientRect();
      const ratio = Math.min(Math.max((move.clientX - rect.left) / rect.width, 0), 1);
      const seconds = secondsFor(ratio);
      /* Follows the pointer with no transition — a lagging handle feels broken. */
      node.style.left = `calc(${positionFor(seconds)}% - (var(--handle-width) / 2))`;
      if (edge === "start") {
        el("span").style.left = `${positionFor(seconds)}%`;
        el("tc-start").textContent = formatTimecode(seconds);
      } else {
        el("tc-end").textContent = formatTimecode(seconds);
      }
      node.dataset.pending = String(seconds);
    };

    const onUp = () => {
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerup", onUp);
      const pending = Number(node.dataset.pending);
      delete node.dataset.pending;
      if (Number.isFinite(pending)) {
        commitBounds(
          edge === "start" ? pending : current.start,
          edge === "end" ? pending : current.end,
        );
      }
    };

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerup", onUp);
  });

  /* Keyboard equivalence is why the handles are focusable sliders rather than
   * pointer-only affordances. */
  node.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 1.0 : 0.1;
    let delta = 0;
    if (event.key === "ArrowLeft") delta = -step;
    else if (event.key === "ArrowRight") delta = step;
    else return;
    event.preventDefault();
    commitBounds(
      edge === "start" ? current.start + delta : current.start,
      edge === "end" ? current.end + delta : current.end,
    );
  });
}

function renderCaptions() {
  const list = el("caption-list");
  list.innerHTML = "";

  for (const line of current.lines) {
    const item = document.createElement("li");
    item.className = "caption-row";
    item.dataset.start = String(line.start);
    item.dataset.end = String(line.end);

    const time = document.createElement("span");
    time.className = "caption-time";
    time.textContent = formatTimecode(line.start - current.start);

    const input = document.createElement("input");
    input.type = "text";
    input.value = line.text;
    input.setAttribute("aria-label", `Caption at ${time.textContent}`);

    input.addEventListener("change", async () => {
      const text = input.value.trim();
      if (!text) {
        input.setAttribute("aria-invalid", "true");
        el("timeline-message").textContent = "A caption line cannot be empty.";
        input.value = line.text;
        return;
      }
      try {
        const body = await api("/api/caption", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clip_index: current.index, line_index: line.index, text }),
        });
        input.removeAttribute("aria-invalid");
        el("timeline-message").textContent = "";
        current = body.clip;
        clips[current.index] = current;
        renderCaptions();
      } catch (error) {
        input.setAttribute("aria-invalid", "true");
        el("timeline-message").textContent = error.message;
        input.value = line.text;
      }
    });

    item.append(time, input);
    list.appendChild(item);
  }
}

/* Highlight the line under the playhead. Colour is not the only signal — the
 * timecode changes weight too. */
el("preview").addEventListener("timeupdate", () => {
  if (!current) return;
  const now = el("preview").currentTime + current.start;
  for (const row of el("caption-list").children) {
    const start = Number(row.dataset.start);
    const end = Number(row.dataset.end);
    row.classList.toggle("is-active", now >= start && now <= end);
  }
});

el("export").addEventListener("click", async () => {
  el("export").disabled = true;
  el("export-note").textContent = "Rendering…";
  try {
    await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clip_index: current.index }),
    });
    startPolling();
  } catch (error) {
    el("export-note").textContent = "";
    el("timeline-message").textContent = error.message;
    el("export").disabled = false;
  }
});
