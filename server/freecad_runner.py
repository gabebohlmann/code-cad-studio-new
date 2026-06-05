# server/freecad_runner.py

import os
import uuid
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Dict

def build_freecad_env(extra_pythonpath: str | None = None) -> dict:
    """
    Builds the environment used by the FreeCAD subprocess.

    This is where we inject external Python packages, like build123d,
    into FreeCAD's embedded Python interpreter.
    """
    env = os.environ.copy()

    paths = []

    if extra_pythonpath:
        paths.append(os.path.abspath(os.path.expanduser(extra_pythonpath)))

    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        paths.extend([p for p in existing_pythonpath.split(os.pathsep) if p])

    deduped = []
    for p in paths:
        if p and p not in deduped:
            deduped.append(p)

    env["PYTHONPATH"] = os.pathsep.join(deduped)

    return env

def norm(p: str) -> str:
    """
    Normalizes a file path to use forward slashes and absolute positioning.

    Args:
        p (str): Input path.

    Returns:
        str: Normalized absolute path.
    """
    return os.path.abspath(p).replace("\\", "/")


@dataclass
class Job:
    """
    Data container representing a single rendering job state.

    Attributes:
        id (str): Unique UUID string for the job.
        status (str): Current state ('queued', 'running', 'done', 'error').
        logs (List[str]): Captured stdout/stderr lines from the FreeCAD subprocess.
        error (str | None): Error message if the job failed.
        mesh_path (str | None): Absolute path to the generated STL file.
        shapes_path (str | None): Absolute path to the generated JSON geometry file.
        code_path (str | None): Absolute path to the input Python script file.
        work_dir (str | None): Absolute path to the temporary directory holding artifacts.
    """
    id: str
    status: str = "queued"  # queued|running|done|error
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    mesh_path: Optional[str] = None
    shapes_path: Optional[str] = None
    code_path: Optional[str] = None
    work_dir: Optional[str] = None
    trace_path: Optional[str] = None
    ir_path: Optional[str] = None
    pickmap_path: Optional[str] = None


class JobStore:
    """
    Simple in-memory database for tracking rendering jobs.

    Attributes:
        jobs (Dict[str, Job]): Dictionary mapping job IDs to Job objects.
    """
    def __init__(self):
        """Initializes an empty job store."""
        self.jobs: Dict[str, Job] = {}

    """
    Creates a new Job with a unique ID and registers it in the store.

    Returns:
        Job: The newly created job instance (status='queued').
    """
    def create(self) -> Job:
        """
        Creates a new Job with a unique ID and registers it in the store.

        Returns:
            Job: The newly created job instance (status='queued').
        """
        jid = str(uuid.uuid4())
        j = Job(id=jid)
        self.jobs[jid] = j
        return j

    def get(self, jid: str) -> Optional[Job]:
        """
        Retrieves a job by its ID.

        Args:
            jid (str): The unique job identifier.

        Returns:
            Job | None: The job object if found, else None.
        """
        return self.jobs.get(jid)


def run_freecad_job(
    freecad_cmd: str,
    run_py: str,
    code_text: str,
    mesh_quality: str = "preview",
    verbose: bool = True,
    extra_pythonpath: str | None = None,
) -> Job:
    """
    Synchronously executes a FreeCAD rendering job in a subprocess.

    This function:
    1. Creates a temporary working directory.
    2. Writes the user's code to `input.py`.
    3. Launches `FreeCADCmd.exe` with `cli/run.py` to process the file.
    4. Captures stdout/stderr into the job logs.
    5. Verifies the output artifacts (JSON/STL) exist.

    Note:
        Uses the "Option A" pass style for FreeCAD arguments:
        `FreeCADCmd.exe <run.py> --pass "<all script args in one string>"`
        This avoids argument parsing issues inherent to FreeCAD's CLI.

    Args:
        freecad_cmd (str): Path to the `FreeCADCmd` executable.
        run_py (str): Path to the `cli/run.py` script.
        code_text (str): The Python source code to render.
        mesh_quality (str, optional): tessellation quality ('preview' or 'final'). Defaults to "preview".
        verbose (bool, optional): If True, passes the `--verbose` flag to the runner. Defaults to True.

    Returns:
        Job: A completed Job object with status set to 'done' or 'error'.
    """
    job = Job(id=str(uuid.uuid4()), status="running")

    work_dir = tempfile.mkdtemp(prefix="codecad_")
    job.work_dir = work_dir

    try:
        code_path = norm(os.path.join(work_dir, "input.py"))
        mesh_path = norm(os.path.join(work_dir, "out.stl"))
        shapes_path = norm(os.path.join(work_dir, "out.json"))
        log_path = norm(os.path.join(work_dir, "run.log"))
        trace_path = norm(os.path.join(work_dir, "freecad_trace.py"))
        ir_path = norm(os.path.join(work_dir, "codecad_ir.json"))
        pickmap_path = norm(os.path.join(work_dir, "codecad_pickmap.json"))

        job.code_path = code_path
        job.mesh_path = mesh_path
        job.shapes_path = shapes_path
        job.trace_path = trace_path
        job.ir_path = ir_path
        job.pickmap_path = pickmap_path

        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code_text)

        # NOTE: do NOT embed extra quotes here. This is one single string argument.
        pass_args = (
            f"--code {code_path} "
            f"--mesh {mesh_path} "
            f"--mesh-quality {mesh_quality} "
            f"--shapes {shapes_path} "
            f"--trace {trace_path} "
            f"--ir {ir_path} "
            f"--pickmap {pickmap_path}"
        )
        if verbose:
            pass_args += " --verbose"

        cmd = [
            norm(freecad_cmd),
            norm(run_py),
            "--pass",
            pass_args,
        ]

        env = os.environ.copy()
        # Make sure run.py can log even if stdout capture is weird
        env["CODECAD_LOG"] = log_path
        # Encourage unbuffered python output
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"

        job.logs.append("[server] launching FreeCADCmd:")
        job.logs.append(" ".join(cmd))
        job.logs.append(f"[server] work_dir={work_dir}")
        job.logs.append(f"[server] log_file={log_path}")

        freecad_env = build_freecad_env(extra_pythonpath)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=freecad_env,
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            job.logs.append(line.rstrip("\n"))

        rc = proc.wait()
        job.logs.append(f"[server] rc={rc}")

        # Always list directory contents for postmortem
        try:
            job.logs.append("[server] work_dir files: " + ", ".join(os.listdir(work_dir)))
        except Exception as e:
            job.logs.append(f"[server] listdir failed: {e}")

        if rc != 0:
            job.status = "error"
            job.error = f"FreeCADCmd exited with code {rc}"
            return job

        # Keep STL check (useful for downloads), but require shapes for the viewer path.
        if not os.path.exists(shapes_path):
            job.status = "error"
            job.error = "Shapes not created (out.json missing)"
            return job

        # STL is optional for the web viewer path; warn only.
        if not os.path.exists(mesh_path):
            job.logs.append("[server] WARNING: out.stl missing (viewer can still use out.json)")

        job.status = "done"
        return job

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        return job

    # NOTE: keep work_dir around so artifacts/log can be downloaded later.