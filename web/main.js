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
const elCodecadPickmap = document.getElementById("codecadPickmap");
const elSelectionSummary = document.getElementById("selectionSummary");
const btnShowPickmapTab = document.getElementById("showPickmapTab");
const btnCopyDebugTab = document.getElementById("copyDebugTab");

let currentPickmap = null;
let currentSelection = null;
let lastFacePickAt = 0;
let viewerPointerDown = null;
let viewerDragInProgress = false;

const FACE_CLICK_MAX_MOVE_PX = 4;
let activeDebugTab = "log";

const btnShowLogTab = document.getElementById("showLogTab");
const btnShowTraceTab = document.getElementById("showTraceTab");
const btnShowIrTab = document.getElementById("showIrTab");
const elSnippetToolbar = document.getElementById("snippetToolbar");
const btnPreview = document.getElementById("renderPreview");
const btnFinal = document.getElementById("renderFinal");
const btnClearLog = document.getElementById("clearLog");
const btnClearCode = document.getElementById("clearCode");
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
  activeDebugTab = which || "log";

  if (elLog) elLog.style.display = activeDebugTab === "log" ? "" : "none";
  if (elFreecadTrace) elFreecadTrace.style.display = activeDebugTab === "trace" ? "" : "none";
  if (elCodecadIr) elCodecadIr.style.display = activeDebugTab === "ir" ? "" : "none";
  if (elCodecadPickmap) elCodecadPickmap.style.display = activeDebugTab === "pickmap" ? "" : "none";

  btnShowLogTab?.classList.toggle("active", activeDebugTab === "log");
  btnShowTraceTab?.classList.toggle("active", activeDebugTab === "trace");
  btnShowIrTab?.classList.toggle("active", activeDebugTab === "ir");
  btnShowPickmapTab?.classList.toggle("active", activeDebugTab === "pickmap");
}

function getActiveDebugElement() {
  if (activeDebugTab === "trace") return elFreecadTrace;
  if (activeDebugTab === "ir") return elCodecadIr;
  if (activeDebugTab === "pickmap") return elCodecadPickmap;
  return elLog;
}

function getActiveDebugLabel() {
  if (activeDebugTab === "trace") return "FreeCAD Cmd";
  if (activeDebugTab === "ir") return "CodeCAD JSON";
  if (activeDebugTab === "pickmap") return "Selection";
  return "Log";
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }

  // Fallback for localhost / older browsers.
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();

  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
}

async function copyCurrentDebugView() {
  const el = getActiveDebugElement();
  const label = getActiveDebugLabel();

  if (!el) {
    log(`copy failed: no active debug panel for ${label}`);
    return;
  }

  const text = el.textContent || "";

  if (!text.trim()) {
    log(`copy skipped: ${label} is empty`);
    return;
  }

  try {
    await copyTextToClipboard(text);
    setStatus(`copied ${label}`);
    log(`copied ${label} debug text`);

    btnCopyDebugTab?.classList.add("copied");
    setTimeout(() => {
      btnCopyDebugTab?.classList.remove("copied");
    }, 1500);
  } catch (e) {
    setStatus("copy failed");
    log(`copy failed: ${e}`);
  }
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

# Box
part = Box(10, 10, 10)
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


function summarizePickmapObject(obj) {
  if (!obj) return "Nothing selected";

  const shape = obj.shape || {};
  const src = obj.source || {};

  return [
    `Object: ${obj.name || obj.object_id || "unknown"}`,
    `Type: ${src.freecad_type || "unknown"}`,
    `Faces: ${shape.faces ?? "?"}`,
    `Edges: ${shape.edges ?? "?"}`,
    `Vertices: ${shape.vertices ?? "?"}`,
    `Volume: ${shape.volume ?? "?"}`,
  ].join(" | ");
}

function summarizePickmapFace(objectRecord, faceRecord) {
  if (!objectRecord || !faceRecord) return "Nothing selected";

  const selector =
    (faceRecord.selector_candidates || [])[0] ||
    `${objectRecord.name || objectRecord.object_id || "part"}.faces()[${Number(faceRecord.index || 1) - 1}]`;

  const normal = (faceRecord.normal || [])
    .map((n) => Number(n).toFixed(3))
    .join(", ");

  const center = (faceRecord.center || [])
    .map((n) => Number(n).toFixed(3))
    .join(", ");

  const area =
    faceRecord.area !== undefined && faceRecord.area !== null
      ? Number(faceRecord.area).toFixed(3)
      : "?";

  return [
    `Face: ${faceRecord.freecad_ref || faceRecord.face_id || "unknown"}`,
    `Object: ${objectRecord.name || objectRecord.object_id || "unknown"}`,
    `Surface: ${faceRecord.surface_type || "unknown"}`,
    `Area: ${area}`,
    `Center: [${center}]`,
    `Normal: [${normal}]`,
    `Selector: ${selector}`,
  ].join(" | ");
}

function clearFacePickOverlay() {
  // Face picking is now native to the Shapes JSON artifact.
  // Each CAD face is emitted as a nearly transparent three-cad-viewer part.
}

function rebuildFacePickOverlay() {
  // No browser-side overlay required.
  const faceCount = (currentPickmap?.objects || []).reduce(
    (acc, obj) => acc + (obj.faces || []).length,
    0
  );

  log(`native face pick parts loaded: ${faceCount} faces`);
}

function pointerDistancePx(a, event) {
  if (!a) return Infinity;

  const dx = Number(event.clientX) - Number(a.x);
  const dy = Number(event.clientY) - Number(a.y);

  return Math.sqrt(dx * dx + dy * dy);
}

function onViewerPointerDown(event) {
  if (event.button !== undefined && event.button !== 0) {
    viewerPointerDown = null;
    viewerDragInProgress = false;
    return;
  }

  viewerPointerDown = {
    x: event.clientX,
    y: event.clientY,
    time: Date.now(),
  };

  viewerDragInProgress = false;
}

function onViewerPointerMove(event) {
  if (!viewerPointerDown) return;

  const moved = pointerDistancePx(viewerPointerDown, event);

  if (moved > FACE_CLICK_MAX_MOVE_PX) {
    viewerDragInProgress = true;
  }
}

function onViewerPointerUp() {
  // Do not clear viewerDragInProgress immediately. Native three-cad-viewer
  // change/pick events may fire just after pointerup.
  setTimeout(() => {
    viewerPointerDown = null;
    viewerDragInProgress = false;
  }, 150);
}

function installViewerInteractionGuards() {
  const canvas =
    document.querySelector("#viewer canvas") ||
    document.querySelector("canvas");

  const targets = [canvas, elViewer].filter(Boolean);

  for (const target of targets) {
    target.removeEventListener("pointerdown", onViewerPointerDown, true);
    target.removeEventListener("pointermove", onViewerPointerMove, true);
    target.removeEventListener("pointerup", onViewerPointerUp, true);
    target.removeEventListener("pointerleave", onViewerPointerUp, true);

    target.addEventListener("pointerdown", onViewerPointerDown, true);
    target.addEventListener("pointermove", onViewerPointerMove, true);
    target.addEventListener("pointerup", onViewerPointerUp, true);
    target.addEventListener("pointerleave", onViewerPointerUp, true);
  }
}

function extractPickString(pick) {
  if (!pick) return "";

  const candidates = [
    pick.id,
    pick.name,
    pick.path,
    pick.objectId,
    pick.partId,
    pick.fullPath,
    pick?.object?.id,
    pick?.object?.name,
    pick?.object?.path,
    pick?.object?.userData?.id,
    pick?.object?.userData?.partId,
    pick?.object?.userData?.objectId,
  ];

  return candidates
    .filter((x) => x !== undefined && x !== null)
    .map((x) => String(x))
    .join(" ");
}

function extractFaceRefFromPick(pick) {
  const raw = extractPickString(pick);

  // Matches:
  //   /Group/CodeCAD_FacePick_Face5
  //   CodeCAD_FacePick_Face5
  //   Face5
  const m =
    raw.match(/CodeCAD_FacePick_Face(\d+)/) ||
    raw.match(/\bFace(\d+)\b/);

  if (!m) return null;

  return `Face${Number(m[1])}`;
}

function findPickmapFaceByRef(faceRef) {
  if (!faceRef || !currentPickmap) return null;

  for (const objectRecord of currentPickmap.objects || []) {
    for (const faceRecord of objectRecord.faces || []) {
      if (faceRecord.freecad_ref === faceRef) {
        return {
          object: objectRecord,
          face: faceRecord,
        };
      }
    }
  }

  return null;
}

function handleNativeViewerPick(pick) {
  if (viewerDragInProgress) {
    return;
  }

  const faceRef = extractFaceRefFromPick(pick);
  const hit = findPickmapFaceByRef(faceRef);

  if (hit) {
    lastFacePickAt = Date.now();

    setSelection({
      kind: "face",
      render_revision: currentPickmap?.render_revision,
      object: hit.object,
      face: hit.face,
      raw_pick: pick,
    });

    console.debug("selected native face", {
      face: hit.face.freecad_ref,
      face_id: hit.face.face_id,
      raw_pick: pick,
    });

    showDebugTab("pickmap");
    return;
  }

  // Fallback: object-level selection.
  const renderedId = extractRenderedPartIdFromPick(pick);

  const object =
    findPickmapObjectForRenderedPart(renderedId) ||
    findPickmapObjectForRenderedPart("/Group/Part_0") ||
    findPickmapObjectForRenderedPart("Part_0");

  if (!object) return;

  setSelection({
    kind: "object",
    render_revision: currentPickmap?.render_revision,
    render_part_id: renderedId || "/Group/Part_0",
    object,
    raw_pick: pick,
  });

  showDebugTab("pickmap");
}

function setSelection(selection) {
  currentSelection = selection || null;

  if (!elSelectionSummary) return;

  if (!currentSelection) {
    elSelectionSummary.textContent = "Nothing selected";
    return;
  }

  if (currentSelection.kind === "face") {
    elSelectionSummary.textContent = summarizePickmapFace(
      currentSelection.object,
      currentSelection.face
    );
    return;
  }

  elSelectionSummary.textContent = summarizePickmapObject(currentSelection.object);
}

function findPickmapObjectForRenderedPart(renderPartIdOrName) {
  if (!currentPickmap || !Array.isArray(currentPickmap.objects)) return null;

  const wanted = String(renderPartIdOrName || "");

  return currentPickmap.objects.find((obj) => {
    const src = obj.source || {};
    return (
      obj.object_id === wanted ||
      obj.name === wanted ||
      src.render_part_id === wanted ||
      src.render_part_name === wanted ||
      wanted.endsWith(String(src.render_part_name || "")) ||
      wanted.endsWith(String(obj.object_id || ""))
    );
  }) || null;
}

function extractRenderedPartIdFromPick(pick) {
  if (!pick) return null;

  // three-cad-viewer pick objects can vary by version. Be permissive.
  const candidates = [
    pick.id,
    pick.name,
    pick.path,
    pick.objectId,
    pick.partId,
    pick?.object?.id,
    pick?.object?.name,
    pick?.object?.userData?.id,
    pick?.object?.userData?.partId,
    pick?.object?.userData?.objectId,
  ];

  for (const c of candidates) {
    if (c !== undefined && c !== null && String(c).trim()) {
      return String(c);
    }
  }

  return null;
}

function handleViewerPick(pick) {
  if (Date.now() - lastFacePickAt < 250) {
    return;
  }

  const renderedId = extractRenderedPartIdFromPick(pick);

  // Current Shapes JSON exports one rendered part: /Group/Part_0.
  // If three-cad-viewer does not expose an id in the pick event, use that
  // as the MVP fallback.
  const object =
    findPickmapObjectForRenderedPart(renderedId) ||
    findPickmapObjectForRenderedPart("/Group/Part_0") ||
    findPickmapObjectForRenderedPart("Part_0");

  if (!object) {
    setSelection(null);
    log(`pick received but no pickmap object matched: ${JSON.stringify(pick)}`);
    return;
  }

  setSelection({
    kind: "object",
    render_revision: currentPickmap?.render_revision,
    render_part_id: renderedId || "/Group/Part_0",
    object,
    raw_pick: pick,
  });

  showDebugTab("pickmap");
}

/**
 * Callback triggered by the 3D Viewer when the scene changes (e.g., selection).
 * * @param {object} change - The event data from the viewer.
 */
function notifyChange(change) {
  const pick =
    change?.lastPick?.new ||
    change?.lastPick ||
    change?.pick ||
    change?.selected ||
    null;

  if (!pick) return;

  handleNativeViewerPick(pick);
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

  setTimeout(installViewerInteractionGuards, 0);

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

async function loadPickmap(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/pickmap`);
  if (!res.ok) {
    return {
      schema: "codecad.pickmap.v0",
      message: "CodeCAD pickmap unavailable",
      objects: [],
    };
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

  setTimeout(installViewerInteractionGuards, 0);
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

function clearCodeWindowConfirmed() {
  const ok = window.confirm(
    "Clear the CodeCAD editor?\n\nThis will remove the code from the browser editor. The web render backend is job-based, so this does not delete any persistent FreeCAD document."
  );

  if (!ok) return;

  elCode.value = "";
  lastReplaceSnippet = null;

  if (elFreecadTrace) {
    elFreecadTrace.textContent = "# FreeCAD Cmd trace will appear after render.";
  }

  if (elCodecadIr) {
    elCodecadIr.textContent = '{\n  "schema": "codecad.ir.v0",\n  "message": "CodeCAD JSON will appear after render."\n}';
  }

  currentPickmap = null;
  currentSelection = null;
  clearFacePickOverlay();

  if (elCodecadPickmap) {
    elCodecadPickmap.textContent = '{\n  "schema": "codecad.pickmap.v0",\n  "message": "Pickmap will appear after render."\n}';
  }

  if (elSelectionSummary) {
    elSelectionSummary.textContent = "Nothing selected";
  }

  try {
    viewer?.clear?.();
  } catch {
    // ignore
  }

  setStatus("cleared");
  log("code window cleared");
  elCode.focus();
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

    // Seed lastReplaceSnippet with the "box" snippet so the origin toggle works
    // immediately on page load — the default starting code in the editor is a Box.
    if (!lastReplaceSnippet) {
      const boxSnip = snippets.find((s) => s.key === "box");
      if (boxSnip) lastReplaceSnippet = boxSnip;
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

    currentPickmap = await loadPickmap(job_id);

    if (elCodecadPickmap) {
      elCodecadPickmap.textContent = JSON.stringify(currentPickmap, null, 2);
    }

    setSelection(null);
    rebuildFacePickOverlay();
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
btnShowPickmapTab?.addEventListener("click", () => showDebugTab("pickmap"));
btnCopyDebugTab?.addEventListener("click", copyCurrentDebugView);

elCode.addEventListener("click", moveCodeCursorToBottom);
btnPreview.addEventListener("click", () => render("preview"));
btnFinal.addEventListener("click", () => render("final"));
btnClearCode?.addEventListener("click", clearCodeWindowConfirmed);
btnClearLog.addEventListener("click", () => (elLog.textContent = ""));
showDebugTab("log");
setStatus("idle");