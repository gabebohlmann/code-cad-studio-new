// web/main.js

/**
 * @fileoverview Frontend logic for Code-CAD Studio.
 * * Integrates the 'three-cad-viewer' library to display 3D geometry generated
 * by the FreeCAD backend. It manages the Job submission lifecycle (Submit -> Poll -> Render).
 */

import {
  Viewer,
  Display,
} from "https://cdn.jsdelivr.net/npm/three-cad-viewer@3.5.1/dist/three-cad-viewer.esm.min.js";

const API = "/api/v1";

// UI Element References
const elViewer = document.getElementById("viewer");
const elCode = document.getElementById("code");
const elLog = document.getElementById("log");
const elStatus = document.getElementById("status");
const elSnippetToolbar = document.getElementById("snippetToolbar");
const btnPreview = document.getElementById("renderPreview");
const btnFinal = document.getElementById("renderFinal");
const btnClearLog = document.getElementById("clearLog");

/**
 * Appends a line of text to the on-screen log console.
 * Automatically scrolls to the bottom.
 * * @param {string} line - The message to append.
 */
function log(line) {
  elLog.textContent += line + "\n";
  elLog.scrollTop = elLog.scrollHeight;
}

/**
 * Updates the small status badge in the sidebar.
 * * @param {string} s - The status text (e.g., "running...", "done").
 */
function setStatus(s) {
  elStatus.textContent = s;
}

/**
 * Toggles the disabled state of the render buttons.
 * Used to prevent double-submissions while a job is running.
 * * @param {boolean} b - If true, buttons are disabled.
 */
function setBusy(b) {
  btnPreview.disabled = b;
  btnFinal.disabled = b;
}

// Default code example
elCode.value = `from build123d import *

L = 5.0
W = 20.0
H = 3.0

# Box
part = Box(L, W, H)
`;

// --------------------
// three-cad-viewer setup
// --------------------
let viewer = null;
let display = null;

// Configuration objects for the viewer.
// Kept at module level so they can be reused during re-renders.
let displayOptions = null;
let renderOptions = null;
let viewerOptions = null;


/**
 * Callback triggered by the 3D Viewer when the scene changes (e.g., selection).
 * * @param {object} change - The event data from the viewer.
 */
function notifyChange(change) {
  // later on pick/selection events back to FreeCAD.
  try {
    const pick = change?.lastPick?.new;
    if (pick) console.log("picked:", pick);
  } catch {
    // ignore
  }
}

/**
 * Initializes the configuration objects for the 3D viewer.
 * Calculates dimensions based on the DOM element size.
 */
function buildOptions() {
  const w = Math.max(200, elViewer.clientWidth || 800);
  const h = Math.max(200, elViewer.clientHeight || 600);

  displayOptions = {
    cadWidth: w,
    height: h,
    treeWidth: 260,
    theme: "dark",
    pinning: true,
    keymap: {
      shift: "shiftKey",
      ctrl: "ctrlKey",
      meta: "metaKey",
    },
  };

  // Rendering aesthetics (Material properties)
  renderOptions = {
    ambientIntensity: 1.0,
    directIntensity: 1.1,
    metalness: 0.3,
    roughness: 0.65,
    edgeColor: 0x707070,
    defaultOpacity: 1.0,
    normalLen: 0,
  };

  // Camera settings
  viewerOptions = {
    target: [0, 0, 0],
    up: "Z",
  };
}

/**
 * Instantiates the three-cad-viewer Display and Viewer objects.
 * Clears the DOM element before creation to prevent duplicates on resize.
 * * @returns {Viewer} The initialized Viewer instance.
 */
function createCadViewer() {
  buildOptions();

  // wipe old DOM contents
  elViewer.innerHTML = "";

  // create display + viewer exactly as the upstream skeleton does
  display = new Display(elViewer, displayOptions);
  viewer = new Viewer(display, viewerOptions, notifyChange);

  return viewer;
}

// Initial setup
createCadViewer();

// Handle Window Resize with Debounce
let _resizeTimer = null;
window.addEventListener("resize", () => {
  // Debounce to avoid thrashing while resizing.
  if (_resizeTimer) clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => {
    try {
      viewer?.clear?.();
    } catch {
      // ignore
    }
    createCadViewer();
  }, 120);
});

// --------------------
// API calls
// --------------------

/**
 * Submits a new rendering job to the backend.
 * * @param {string} code - The Python source code.
 * @param {string} mesh_quality - 'preview' or 'final'.
 * @returns {Promise<{job_id: string}>} The created job ID.
 */
async function createJob(code, mesh_quality) {
  const res = await fetch(`${API}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, mesh_quality, verbose: true }),
  });

  if (!res.ok) {
    const t = await res.text();
    throw new Error(`POST /jobs failed (${res.status}): ${t}`);
  }
  return await res.json(); // { job_id }
}

/**
 * Polls the status of a specific job.
 * * @param {string} jobId - The Job ID to check.
 * @returns {Promise<object>} The job status object.
 */
async function getJob(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`GET /jobs/${jobId} failed (${res.status}): ${t}`);
  }
  return await res.json();
}

/**
 * Fetches the generated JSON geometry for a completed job.
 * * @param {string} jobId - The Job ID.
 * @returns {Promise<object>} The three-cad-viewer JSON protocol object.
 */
async function loadShapes(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/shapes`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`GET /jobs/${jobId}/shapes failed (${res.status}): ${t}`);
  }
  return await res.json();
}

/**
 * Renders the provided shapes in the 3D viewer.
 * * @param {object} shapes - The JSON geometry data.
 */
function showShapes(shapes) {
  if (!viewer) createCadViewer();

  try {
    viewer.clear?.();
  } catch {
    // ignore
  }

  // IMPORTANT: pass renderOptions + viewerOptions like the upstream skeleton 
  viewer.render(shapes, renderOptions, viewerOptions);
}

function moveCodeCursorToBottom() {
  const pos = elCode.value.length;
  try {
    elCode.focus();
    elCode.setSelectionRange(pos, pos);
    elCode.scrollTop = elCode.scrollHeight;
  } catch {
    // ignore
  }
}

function appendCodeAtBottom(code) {
  const current = elCode.value.trimEnd();
  const snippet = String(code || "").replace(/^\n+|\n+$/g, "");

  if (current) {
    elCode.value = `${current}\n\n${snippet}\n`;
  } else {
    elCode.value = `${snippet}\n`;
  }

  moveCodeCursorToBottom();
}

function insertSnippet(snip) {
  if (!snip || !snip.code) return;

  if (snip.mode === "replace") {
    elCode.value = String(snip.code).trimEnd() + "\n";
    moveCodeCursorToBottom();
    return;
  }

  appendCodeAtBottom(snip.code);
}

async function loadSnippets() {
  if (!elSnippetToolbar) return;

  try {
    const res = await fetch(`${API}/snippets`);
    if (!res.ok) throw new Error(`GET /snippets failed (${res.status})`);

    const data = await res.json();
    const snippets = data.snippets || [];

    const groups = new Map();
    for (const snip of snippets) {
      if (!groups.has(snip.group)) groups.set(snip.group, []);
      groups.get(snip.group).push(snip);
    }

    elSnippetToolbar.innerHTML = "";

    for (const [groupName, groupSnippets] of groups.entries()) {
      const group = document.createElement("div");
      group.className = "snippet-group";

      const label = document.createElement("span");
      label.className = "snippet-group-label";
      label.textContent = groupName + ": ";
      group.appendChild(label);

      for (const snip of groupSnippets) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = snip.label;
        btn.addEventListener("click", () => insertSnippet(snip));
        group.appendChild(btn);
      }

      elSnippetToolbar.appendChild(group);
    }
  } catch (e) {
    log(`snippet load failed: ${e}`);
  }
}

// --------------------
// Render loop (job submit + poll + show)
// --------------------

/**
 * Main orchestration function.
 * 1. Submits the code to the server.
 * 2. Polls the job status until 'done' or 'error'.
 * 3. Fetches the result.
 * 4. Updates the 3D viewer.
 * * @param {string} mesh_quality - 'preview' or 'final'.
 */
async function render(mesh_quality) {
  setBusy(true);
  setStatus("submitting…");
  log(`--- render (${mesh_quality}) ---`);

  try {
    const { job_id } = await createJob(elCode.value, mesh_quality);
    log(`job_id: ${job_id}`);

    setStatus("running…");

    let lastLogLen = 0;

    while (true) {
      const j = await getJob(job_id);

      // stream logs (poll)
      const logs = j.logs || [];
      if (logs.length > lastLogLen) {
        for (let i = lastLogLen; i < logs.length; i++) log(logs[i]);
        lastLogLen = logs.length;
      }

      if (j.status === "done") break;
      if (j.status === "error") throw new Error(j.error || "job failed");

      await new Promise((r) => setTimeout(r, 300));
    }

    setStatus("loading shapes…");
    const shapes = await loadShapes(job_id);
    showShapes(shapes);

    setStatus("done");
    log("shapes loaded");
  } catch (e) {
    setStatus("error");
    log(String(e));
    console.error(e);
  } finally {
    setBusy(false);
  }
}

loadSnippets();
elCode.addEventListener("click", moveCodeCursorToBottom);
btnPreview.addEventListener("click", () => render("preview"));
btnFinal.addEventListener("click", () => render("final"));
btnClearLog.addEventListener("click", () => (elLog.textContent = ""));
setStatus("idle");