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
const elFreecadTrace = document.getElementById("freecadTrace");
const elCodecadIr = document.getElementById("codecadIr");

const btnShowLogTab = document.getElementById("showLogTab");
const btnShowTraceTab = document.getElementById("showTraceTab");
const btnShowIrTab = document.getElementById("showIrTab");
const elSnippetToolbar = document.getElementById("snippetToolbar");
const btnPreview = document.getElementById("renderPreview");
const btnFinal = document.getElementById("renderFinal");
const btnClearLog = document.getElementById("clearLog");
const btnOriginB123d = document.getElementById("originB123d");
const btnOriginFreeCAD = document.getElementById("originFreeCAD");

let originMode = localStorage.getItem("codecadOriginMode") || "b123d";

// Tracks the last snippet inserted in "replace" mode so we can re-apply it
// with a different origin variant when the user toggles the origin buttons.
let lastReplaceSnippet = null;

function setOriginMode(mode) {
  originMode = mode === "freecad" ? "freecad" : "b123d";
  localStorage.setItem("codecadOriginMode", originMode);

  if (btnOriginB123d) {
    btnOriginB123d.classList.toggle("active", originMode === "b123d");
    btnOriginB123d.setAttribute("aria-pressed", originMode === "b123d" ? "true" : "false");
  }

  if (btnOriginFreeCAD) {
    btnOriginFreeCAD.classList.toggle("active", originMode === "freecad");
    btnOriginFreeCAD.setAttribute("aria-pressed", originMode === "freecad" ? "true" : "false");
  }

  // Update the toolbar label to always show the current mode
  const elOriginLabel = document.querySelector(".origin-toolbar > span");
  if (elOriginLabel) {
    elOriginLabel.textContent = `Snippet origin (${originMode === "freecad" ? "FreeCAD" : "build123d"}):` ;
  }

  // If a replace-mode snippet is currently in the editor, re-apply it with
  // the new origin so the code window reflects the toggle immediately.
  if (lastReplaceSnippet) {
    const newCode = snippetCodeForOrigin(lastReplaceSnippet);
    if (newCode) {
      elCode.value = String(newCode).trimEnd() + "\n";
      moveCodeCursorToBottom();
    }
  }

  // Log the mode change
  if (elLog) {
    try {
      elLog.textContent += `snippet origin mode: ${originMode === "freecad" ? "FreeCAD" : "build123d"}\n`;
      elLog.scrollTop = elLog.scrollHeight;
    } catch { /* ignore */ }
  }
}

function snippetCodeForOrigin(snip) {
  if (!snip) return "";

  if (originMode === "freecad" && snip.freecad_code) {
    return snip.freecad_code;
  }

  return snip.code || "";
}

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

function showDebugTab(which) {
  if (elLog) elLog.style.display = which === "log" ? "" : "none";
  if (elFreecadTrace) elFreecadTrace.style.display = which === "trace" ? "" : "none";
  if (elCodecadIr) elCodecadIr.style.display = which === "ir" ? "" : "none";

  btnShowLogTab?.classList.toggle("active", which === "log");
  btnShowTraceTab?.classList.toggle("active", which === "trace");
  btnShowIrTab?.classList.toggle("active", which === "ir");
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

async function loadTrace(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/trace`);
  if (!res.ok) {
    return "# FreeCAD Cmd trace unavailable.";
  }
  return await res.text();
}

async function loadIr(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/ir`);
  if (!res.ok) {
    return '{\n  "schema": "codecad.ir.v0",\n  "message": "CodeCAD JSON unavailable"\n}';
  }

  try {
    const data = await res.json();
    return JSON.stringify(data, null, 2);
  } catch {
    return await res.text();
  }
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
  if (!snip) return;

  const code = snippetCodeForOrigin(snip);
  if (!code) return;

  if (snip.mode === "replace") {
    // Remember this snippet so the origin toggle can re-apply it
    lastReplaceSnippet = snip;
    elCode.value = String(code).trimEnd() + "\n";
    moveCodeCursorToBottom();
    return;
  }

  // Append-mode snippets do not replace the editor, so clear the tracker
  // only if the user has started composing (no single-snippet baseline anymore).
  appendCodeAtBottom(code);
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
    log("shapes loaded");

    setStatus("loading debug artifacts…");
    if (elFreecadTrace) {
      elFreecadTrace.textContent = await loadTrace(job_id);
    }
    if (elCodecadIr) {
      elCodecadIr.textContent = await loadIr(job_id);
    }

    setStatus("done");
  } catch (e) {
    setStatus("error");
    log(String(e));
    console.error(e);
  } finally {
    setBusy(false);
  }
}

loadSnippets();
setOriginMode(originMode);

if (btnOriginB123d) {
  btnOriginB123d.addEventListener("click", () => setOriginMode("b123d"));
}

if (btnOriginFreeCAD) {
  btnOriginFreeCAD.addEventListener("click", () => setOriginMode("freecad"));
}

btnShowLogTab?.addEventListener("click", () => showDebugTab("log"));
btnShowTraceTab?.addEventListener("click", () => showDebugTab("trace"));
btnShowIrTab?.addEventListener("click", () => showDebugTab("ir"));

elCode.addEventListener("click", moveCodeCursorToBottom);
btnPreview.addEventListener("click", () => render("preview"));
btnFinal.addEventListener("click", () => render("final"));
btnClearLog.addEventListener("click", () => (elLog.textContent = ""));
showDebugTab("log");
setStatus("idle");