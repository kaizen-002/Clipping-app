"use strict";

/* The page. Vanilla JS, no build step.
 *
 * The domain rules are not duplicated here — bounds and caption edits are sent
 * to the server, which enforces the invariants and returns either the updated
 * clip or a message. Re-implementing the 15-60s rule in the browser would give
 * it two homes and one of them would drift. */

const els = {
  form: document.getElementById("import-form"),
  url: document.getElementById("url"),
  urlError: document.getElementById("url-error"),
  start: document.getElementById("start"),
  status: document.getElementById("status"),
  statusText: document.getElementById("status-text"),
  spinner: document.getElementById("spinner"),
  stageList: document.getElementById("stage-list"),
  editor: document.getElementById("editor"),
  hookSummary: document.getElementById("hook-summary"),
  timeline: document.getElementById("timeline"),
  span: document.getElementById("span"),
  handleStart: document.getElementById("handle-start"),
  handleEnd: document.getElementById("handle-end"),
  tcStart: document.getElementById("tc-start"),
  tcEnd: document.getElementById("tc-end"),
  tcLength: document.getElementById("tc-length"),
  timelineMessage: document.getElementById("timeline-message"),
  captionList: document.getElementById("caption-list"),
  preview: document.getElementById("preview"),
  exportButton: document.getElementById("export"),
};

/* The timeline shows the clip plus context either side, so a handle has
 * somewhere to travel. Without the margin the span fills the track and drag
 * does nothing visible. */
const CONTEXT_SECONDS = 30;

let clip = null;
let view = { min: 0, max: 0 };
let polling = null;

function formatTimecode(seconds) {
  const safe = Math.max(seconds, 0);
  const minutes = Math.floor(safe / 60);
  const rest = (safe % 60).toFixed(1).padStart(4, "0");
  return `${minutes}:${rest}`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `request failed (${response.status})`);
  }
  return body;
}

/* --- Import -------------------------------------------------------------- */

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = els.url.value.trim();

  if (!url) {
    showFieldError("Paste a YouTube URL first.");
    return;
  }
  clearFieldError();

  els.start.disabled = true;
  els.url.disabled = true;
  setStatus("Starting…", "busy");

  try {
    await api("/api/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    startPolling();
  } catch (error) {
    setStatus(error.message, "error");
    els.start.disabled = false;
    els.url.disabled = false;
  }
});

function showFieldError(message) {
  els.urlError.textContent = message;
  els.urlError.hidden = false;
  els.url.setAttribute("aria-invalid", "true");
}

function clearFieldError() {
  els.urlError.hidden = true;
  els.url.removeAttribute("aria-invalid");
}

function setStatus(text, tone) {
  els.statusText.textContent = text;
  els.status.dataset.tone = tone || "";
  els.spinner.classList.toggle("hidden", tone !== "busy");
}

/* --- Polling ------------------------------------------------------------- */

function startPolling() {
  if (polling) clearInterval(polling);
  polling = setInterval(refreshStatus, 1000);
  refreshStatus();
}

async function refreshStatus() {
  let state;
  try {
    state = await api("/api/status");
  } catch (error) {
    setStatus(error.message, "error");
    return;
  }

  if (state.error) {
    clearInterval(polling);
    polling = null;
    setStatus(state.error, "error");
    els.start.disabled = false;
    els.url.disabled = false;
    return;
  }

  if (state.busy) {
    const detail = state.detail ? ` — ${state.detail}` : "";
    setStatus(`${state.stage}${detail}`, "busy");
    return;
  }

  clearInterval(polling);
  polling = null;
  els.start.disabled = false;
  els.url.disabled = false;

  if (state.timings) renderTimings(state.timings);

  if (state.stage === "exported" && state.exported) {
    setStatus(`Exported to ${state.exported}`, "done");
    els.exportButton.disabled = false;
    return;
  }

  if (state.clip) {
    setStatus("Hook found. Adjust and export.", "done");
    loadClip(state.clip);
  }
}

function renderTimings(timings) {
  els.stageList.classList.remove("hidden");
  const total = timings.reduce((sum, t) => sum + t.seconds, 0);
  els.stageList.innerHTML = "";
  for (const timing of timings) {
    els.stageList.appendChild(row(timing.stage, `${timing.seconds.toFixed(1)}s`));
  }
  els.stageList.appendChild(row("TOTAL", `${total.toFixed(1)}s`));
}

function row(left, right) {
  const item = document.createElement("li");
  const a = document.createElement("span");
  a.textContent = left;
  const b = document.createElement("span");
  b.textContent = right;
  item.append(a, b);
  return item;
}

/* --- Clip ---------------------------------------------------------------- */

function loadClip(payload) {
  clip = payload;
  view = {
    min: Math.max(payload.start - CONTEXT_SECONDS, 0),
    max: payload.end + CONTEXT_SECONDS,
  };

  els.editor.classList.remove("hidden");
  if (!els.preview.src) els.preview.src = "/api/video";

  const origin = payload.origin === "heuristic"
    ? "the deterministic fallback, because the model's answer failed validation"
    : "the local model";
  els.hookSummary.innerHTML = "";
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.dataset.origin = payload.origin;
  badge.textContent = payload.origin === "heuristic" ? "Heuristic fallback" : "Model";
  els.hookSummary.append(
    badge,
    document.createTextNode(` Chosen by ${origin}. ${payload.reason}`),
  );
  if (payload.truncated) {
    els.hookSummary.append(
      document.createTextNode(" The span exceeded 60s and was truncated."),
    );
  }

  renderTimeline();
  renderCaptions();
}

function positionFor(seconds) {
  const span = view.max - view.min || 1;
  return ((seconds - view.min) / span) * 100;
}

function secondsFor(ratio) {
  return view.min + ratio * (view.max - view.min);
}

function renderTimeline() {
  const left = positionFor(clip.start);
  const right = positionFor(clip.end);
  els.span.style.left = `${left}%`;
  els.span.style.width = `${Math.max(right - left, 0)}%`;

  /* The handle is a 44px hit area centred on the boundary it controls. */
  els.handleStart.style.left = `calc(${left}% - (var(--handle-width) / 2))`;
  els.handleEnd.style.left = `calc(${right}% - (var(--handle-width) / 2))`;

  els.tcStart.textContent = formatTimecode(clip.start);
  els.tcEnd.textContent = formatTimecode(clip.end);
  els.tcLength.textContent = `${clip.duration.toFixed(1)}s`;

  for (const [handle, value] of [
    [els.handleStart, clip.start],
    [els.handleEnd, clip.end],
  ]) {
    handle.setAttribute("aria-valuemin", view.min.toFixed(1));
    handle.setAttribute("aria-valuemax", view.max.toFixed(1));
    handle.setAttribute("aria-valuenow", value.toFixed(1));
    handle.setAttribute("aria-valuetext", formatTimecode(value));
  }
}

async function commitBounds(start, end) {
  try {
    const body = await api("/api/bounds", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start, end }),
    });
    els.timeline.dataset.invalid = "false";
    els.timelineMessage.textContent = "";
    clip = body.clip;
    renderTimeline();
    renderCaptions();
  } catch (error) {
    /* The server rejected it, so the visual state is rolled back to the last
     * accepted clip rather than left showing something that was refused. */
    els.timeline.dataset.invalid = "true";
    els.timelineMessage.textContent = error.message;
    renderTimeline();
  }
}

/* --- Dragging ------------------------------------------------------------ */

for (const [handle, edge] of [[els.handleStart, "start"], [els.handleEnd, "end"]]) {
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);

    const onMove = (moveEvent) => {
      const rect = els.timeline.getBoundingClientRect();
      const ratio = Math.min(Math.max((moveEvent.clientX - rect.left) / rect.width, 0), 1);
      const seconds = secondsFor(ratio);
      /* Follows the pointer with no transition — design.md motion table. */
      if (edge === "start") {
        els.span.style.left = `${positionFor(seconds)}%`;
        els.tcStart.textContent = formatTimecode(seconds);
      } else {
        els.tcEnd.textContent = formatTimecode(seconds);
      }
      handle.style.left = `calc(${positionFor(seconds)}% - (var(--handle-width) / 2))`;
      handle.dataset.pending = String(seconds);
    };

    const onUp = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      const pending = Number(handle.dataset.pending);
      delete handle.dataset.pending;
      if (Number.isFinite(pending)) {
        commitBounds(
          edge === "start" ? pending : clip.start,
          edge === "end" ? pending : clip.end,
        );
      }
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });

  /* Keyboard equivalence is why the handles are focusable controls with slider
   * semantics rather than pointer-only affordances. */
  handle.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 1.0 : 0.1;
    let delta = 0;
    if (event.key === "ArrowLeft") delta = -step;
    else if (event.key === "ArrowRight") delta = step;
    else return;

    event.preventDefault();
    commitBounds(
      edge === "start" ? clip.start + delta : clip.start,
      edge === "end" ? clip.end + delta : clip.end,
    );
  });
}

/* --- Captions ------------------------------------------------------------ */

function renderCaptions() {
  els.captionList.innerHTML = "";

  clip.lines.forEach((line) => {
    const item = document.createElement("li");
    item.className = "caption-row";
    item.dataset.start = String(line.start);
    item.dataset.end = String(line.end);

    const time = document.createElement("span");
    time.className = "caption-time";
    time.textContent = formatTimecode(line.start - clip.start);

    const input = document.createElement("input");
    input.type = "text";
    input.value = line.text;
    input.setAttribute("aria-label", `Caption at ${formatTimecode(line.start - clip.start)}`);

    input.addEventListener("change", async () => {
      const text = input.value.trim();
      if (!text) {
        input.setAttribute("aria-invalid", "true");
        els.timelineMessage.textContent = "A caption line cannot be empty.";
        input.value = line.text;
        return;
      }
      try {
        const body = await api("/api/caption", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ line_index: line.index, text }),
        });
        input.removeAttribute("aria-invalid");
        els.timelineMessage.textContent = "";
        clip = body.clip;
        renderCaptions();
      } catch (error) {
        input.setAttribute("aria-invalid", "true");
        els.timelineMessage.textContent = error.message;
        input.value = line.text;
      }
    });

    item.append(time, input);
    els.captionList.appendChild(item);
  });
}

/* Highlight the line under the playhead. Colour is not the only signal — the
 * timecode changes weight too, per the colour-independence rule. */
els.preview.addEventListener("timeupdate", () => {
  if (!clip) return;
  const now = els.preview.currentTime + clip.start;
  for (const row of els.captionList.children) {
    const start = Number(row.dataset.start);
    const end = Number(row.dataset.end);
    row.classList.toggle("is-active", now >= start && now <= end);
  }
});

/* --- Export -------------------------------------------------------------- */

els.exportButton.addEventListener("click", async () => {
  els.exportButton.disabled = true;
  setStatus("Rendering…", "busy");
  try {
    await api("/api/export", { method: "POST" });
    startPolling();
  } catch (error) {
    setStatus(error.message, "error");
    els.exportButton.disabled = false;
  }
});
