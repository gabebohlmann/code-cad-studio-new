# server/app.py

import os
import threading
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.freecad_runner import JobStore, run_freecad_job, Job
from core.snippets import list_snippets


def norm(p: str) -> str:
    """
    Normalizes a file path to use forward slashes and absolute positioning.

    Args:
        p (str): Input path.

    Returns:
        str: Normalized absolute path.
    """
    return os.path.abspath(p).replace("\\", "/")


# ---- config (portable to remote later via env vars)
FREECAD_CMD = os.environ.get(
    "FREECAD_CMD",
    r"C:\Program Files\FreeCAD 1.2\bin\FreeCADCmd.exe",
)

# server/ is inside mod_root/server; web/ is mod_root/web; cli/run.py is mod_root/cli/run.py
MOD_ROOT = norm(os.path.dirname(os.path.dirname(__file__)))
RUN_PY = norm(os.path.join(MOD_ROOT, "cli", "run.py"))
WEB_DIR = norm(os.path.join(MOD_ROOT, "web"))

store = JobStore()
jobs: Dict[str, Job] = {}


class RenderRequest(BaseModel):
    """
    Schema for a job submission request.

    Attributes:
        code (str): The Python code to execute.
        mesh_quality (str): Quality of the output mesh ('preview' or 'final'). Defaults to 'preview'.
        verbose (bool): If True, captures and returns full logs. Defaults to True.
    """
    code: str
    mesh_quality: str = "preview"  # preview|final
    verbose: bool = True


class RenderResponse(BaseModel):
    """
    Schema for a job creation response.

    Attributes:
        job_id (str): The unique identifier for the created job.
    """
    job_id: str


app = FastAPI(title="CodeCADStudio API", version="0.1.0")

# CORS is not strictly needed once frontend is served by this same server,
# but leaving it permissive is convenient for dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_in_thread(job_id: str, req: RenderRequest):
    """
    Internal worker function to execute the FreeCAD job in a separate thread.

    Calls the synchronous `run_freecad_job` and updates the global `jobs` dictionary
    with the result.

    Args:
        job_id (str): The ID of the job to update.
        req (RenderRequest): The job parameters.
    """
    result = run_freecad_job(
        freecad_cmd=FREECAD_CMD,
        run_py=RUN_PY,
        code_text=req.code,
        mesh_quality=req.mesh_quality,
        verbose=req.verbose,
    )
    result.id = job_id
    jobs[job_id] = result


# -------------------
# Frontend hosting
# -------------------
# Serve /main.js etc.
if os.path.isdir(WEB_DIR):
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


@app.get("/")
def root():
    """
    Serves the main single-page application entry point.

    Returns:
        FileResponse: The content of `web/index.html`.

    Raises:
        HTTPException: 404 if index.html is missing.
    """
    index = os.path.join(WEB_DIR, "index.html")
    if not os.path.exists(index):
        raise HTTPException(status_code=404, detail="web/index.html not found")
    return FileResponse(index, media_type="text/html")


@app.get("/api/v1/health")
def health():
    """
    System health check endpoint.

    Returns:
        dict: Configuration paths and status to verify server setup.
    """
    return {
        "ok": True,
        "freecad_cmd": norm(FREECAD_CMD),
        "run_py": RUN_PY,
        "web_dir": WEB_DIR,
    }

@app.get("/api/v1/snippets")
def snippets():
    """
    Returns shared code editor snippets for the browser UI.
    """
    return {"snippets": list_snippets()}

@app.post("/api/v1/jobs", response_model=RenderResponse)
def create_job(req: RenderRequest):
    """
    Submits a new rendering job to the queue.

    Spawns a background thread to process the FreeCAD execution without blocking
    the web server.

    Args:
        req (RenderRequest): The job details (code, options).

    Returns:
        RenderResponse: Object containing the new `job_id`.
    """
    j = store.create()
    jobs[j.id] = j

    t = threading.Thread(target=_run_in_thread, args=(j.id, req), daemon=True)
    t.start()

    return RenderResponse(job_id=j.id)


@app.get("/api/v1/jobs/{job_id}")
def job_status(job_id: str) -> Dict[str, Any]:
    """
    Polls the status of a specific job.

    Args:
        job_id (str): The ID of the job to check.

    Returns:
        Dict[str, Any]: Status object containing:
            - id (str): Job ID.
            - status (str): 'queued', 'running', 'done', or 'error'.
            - error (str | None): Error message if failed.
            - logs (list[str]): The last 300 lines of logs.
            - mesh_available (bool): True if STL export succeeded.
            - shapes_available (bool): True if JSON export succeeded.

    Raises:
        HTTPException: 404 if the job ID does not exist.
    """
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")

    tail = j.logs[-300:]
    return {
        "id": j.id,
        "status": j.status,
        "error": j.error,
        "logs": tail,
        "mesh_available": bool(j.mesh_path and os.path.exists(j.mesh_path)),
        "shapes_available": bool(j.shapes_path and os.path.exists(j.shapes_path)),
    }


@app.get("/api/v1/jobs/{job_id}/mesh")
def job_mesh(job_id: str):
    """
    Retrieves the generated STL mesh for a completed job.

    Args:
        job_id (str): The job ID.

    Returns:
        FileResponse: The .stl file download.

    Raises:
        HTTPException:
            - 404 if job or mesh file not found.
            - 409 if job is not yet finished.
    """
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    if j.status != "done":
        raise HTTPException(status_code=409, detail=f"job not done (status={j.status})")
    if not j.mesh_path or not os.path.exists(j.mesh_path):
        raise HTTPException(status_code=404, detail="mesh not found")
    return FileResponse(j.mesh_path, media_type="model/stl", filename="out.stl")


@app.get("/api/v1/jobs/{job_id}/shapes")
def job_shapes(job_id: str):
    """
    Retrieves the generated JSON geometry for three-cad-viewer.

    Args:
        job_id (str): The job ID.

    Returns:
        FileResponse: The .json file download.

    Raises:
        HTTPException:
            - 404 if job or shapes file not found.
            - 409 if job is not yet finished.
    """
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    if j.status != "done":
        raise HTTPException(status_code=409, detail=f"job not done (status={j.status})")
    if not j.shapes_path or not os.path.exists(j.shapes_path):
        raise HTTPException(status_code=404, detail="shapes not found")
    return FileResponse(j.shapes_path, media_type="application/json", filename="out.json")