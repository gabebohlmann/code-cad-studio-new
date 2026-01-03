// web/main.js

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

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
// Three.js viewer setup
// --------------------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);

const camera = new THREE.PerspectiveCamera(
  45,
  elViewer.clientWidth / elViewer.clientHeight,
  0.1,
  100000
);
camera.position.set(120, 80, 120);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(elViewer.clientWidth, elViewer.clientHeight);
elViewer.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

const hemi = new THREE.HemisphereLight(0xffffff, 0x222222, 1.2);
scene.add(hemi);

const dir = new THREE.DirectionalLight(0xffffff, 1.0);
dir.position.set(100, 200, 150);
scene.add(dir);

// helper grid
const grid = new THREE.GridHelper(400, 40);
scene.add(grid);

let currentMesh = null;

function fitCameraToObject(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());

  const maxDim = Math.max(size.x, size.y, size.z);
  const fov = camera.fov * (Math.PI / 180);
  let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
  cameraZ *= 2.2;

  camera.position.set(center.x + cameraZ, center.y + cameraZ * 0.6, center.z + cameraZ);
  camera.near = cameraZ / 100;
  camera.far = cameraZ * 100;
  camera.updateProjectionMatrix();

  controls.target.copy(center);
  controls.update();
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();

window.addEventListener("resize", () => {
  const w = elViewer.clientWidth;
  const h = elViewer.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
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

async function loadMesh(jobId) {
  const url = `${API}/jobs/${jobId}/mesh`;
  const loader = new STLLoader();

  return new Promise((resolve, reject) => {
    loader.load(
      url,
      (geometry) => {
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({ metalness: 0.1, roughness: 0.7 });
        const mesh = new THREE.Mesh(geometry, material);
        resolve(mesh);
      },
      undefined,
      (err) => reject(err)
    );
  });
}

function replaceMesh(mesh) {
  if (currentMesh) {
    scene.remove(currentMesh);
    currentMesh.geometry.dispose();
    // material disposed by GC usually, but let's be explicit if possible
    if (currentMesh.material && currentMesh.material.dispose) currentMesh.material.dispose();
  }
  currentMesh = mesh;
  scene.add(mesh);
  fitCameraToObject(mesh);
}

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

      // stream logs in the simplest way (polling)
      const logs = j.logs || [];
      if (logs.length > lastLogLen) {
        for (let i = lastLogLen; i < logs.length; i++) log(logs[i]);
        lastLogLen = logs.length;
      }

      if (j.status === "done") break;
      if (j.status === "error") throw new Error(j.error || "job failed");

      await new Promise((r) => setTimeout(r, 300));
    }

    setStatus("loading mesh…");
    const mesh = await loadMesh(job_id);
    replaceMesh(mesh);

    setStatus("done");
    log("mesh loaded");
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