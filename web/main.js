// web/main.js

// three-cad-viewer based web UI (no raw three.js)
//
// Requires server endpoint:
//   GET /api/v1/jobs/{job_id}/shapes  -> returns Shapes JSON (protocol v3)

import {
  Viewer,
  Display,
} from "https://cdn.jsdelivr.net/npm/three-cad-viewer@3.5.1/dist/three-cad-viewer.esm.min.js";

const API = "/api/v1";

const elViewer = document.getElementById("viewer");
const elCode = document.getElementById("code");
const elLog = document.getElementById("log");
const elStatus = document.getElementById("status");
const btnPreview = document.getElementById("renderPreview");
const btnFinal = document.getElementById("renderFinal");
const btnClearLog = document.getElementById("clearLog");

function log(line) {
  elLog.textContent += line + "\n";
  elLog.scrollTop = elLog.scrollHeight;
}

function setStatus(s) {
  elStatus.textContent = s;
}

function setBusy(b) {
  btnPreview.disabled = b;
  btnFinal.disabled = b;
}

// Default code
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

// Keep these as module-level so render() can pass them every time.
// (This matches the library's own "Skeleton" example.) :contentReference[oaicite:1]{index=1}
let displayOptions = null;
let renderOptions = null;
let viewerOptions = null;

function notifyChange(change) {
  // You can later forward pick/selection events back to FreeCAD.
  try {
    const pick = change?.lastPick?.new;
    if (pick) console.log("picked:", pick);
  } catch {
    // ignore
  }
}

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

  // Reasonable defaults (similar to README skeleton) :contentReference[oaicite:2]{index=2}
  renderOptions = {
    ambientIntensity: 1.0,
    directIntensity: 1.1,
    metalness: 0.3,
    roughness: 0.65,
    edgeColor: 0x707070,
    defaultOpacity: 1.0,
    normalLen: 0,
  };

  viewerOptions = {
    target: [0, 0, 0],
    up: "Z",
  };
}

function createCadViewer() {
  buildOptions();

  // wipe old DOM contents
  elViewer.innerHTML = "";

  // create display + viewer exactly as the upstream skeleton does :contentReference[oaicite:3]{index=3}
  display = new Display(elViewer, displayOptions);
  viewer = new Viewer(display, viewerOptions, notifyChange);

  return viewer;
}

createCadViewer();

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

async function getJob(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`GET /jobs/${jobId} failed (${res.status}): ${t}`);
  }
  return await res.json();
}

async function loadShapes(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/shapes`);
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`GET /jobs/${jobId}/shapes failed (${res.status}): ${t}`);
  }
  return await res.json();
}

function showShapes(shapes) {
  if (!viewer) createCadViewer();

  try {
    viewer.clear?.();
  } catch {
    // ignore
  }

  // IMPORTANT: pass renderOptions + viewerOptions like the upstream skeleton :contentReference[oaicite:4]{index=4}
  viewer.render(shapes, renderOptions, viewerOptions);
}

// --------------------
// Render loop (job submit + poll + show)
// --------------------
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

btnPreview.addEventListener("click", () => render("preview"));
btnFinal.addEventListener("click", () => render("final"));
btnClearLog.addEventListener("click", () => (elLog.textContent = ""));
setStatus("idle");