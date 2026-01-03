# server/freecad_runner.py

import os
import uuid
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Dict


def norm(p: str) -> str:
    return os.path.abspath(p).replace("\\", "/")


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued|running|done|error
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    mesh_path: Optional[str] = None
    shapes_path: Optional[str] = None
    code_path: Optional[str] = None
    work_dir: Optional[str] = None


class JobStore:
    def __init__(self):
        self.jobs: Dict[str, Job] = {}

    def create(self) -> Job:
        jid = str(uuid.uuid4())
        j = Job(id=jid)
        self.jobs[jid] = j
        return j

    def get(self, jid: str) -> Optional[Job]:
        return self.jobs.get(jid)


def run_freecad_job(
    *,
    freecad_cmd: str,
    run_py: str,
    code_text: str,
    mesh_quality: str = "preview",
    verbose: bool = True,
) -> Job:
    """
    Synchronous worker.

    IMPORTANT: Must use "Option A" pass style:
      FreeCADCmd.exe <run.py> --pass "<all script args in one string>"
    """
    job = Job(id=str(uuid.uuid4()), status="running")

    work_dir = tempfile.mkdtemp(prefix="codecad_")
    job.work_dir = work_dir

    try:
        code_path = norm(os.path.join(work_dir, "input.py"))
        mesh_path = norm(os.path.join(work_dir, "out.stl"))
        shapes_path = norm(os.path.join(work_dir, "out.json"))
        log_path = norm(os.path.join(work_dir, "run.log"))

        job.code_path = code_path
        job.mesh_path = mesh_path
        job.shapes_path = shapes_path

        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code_text)

        # NOTE: do NOT embed extra quotes here. This is one single string argument.
        pass_args = (
            f"--code {code_path} "
            f"--mesh {mesh_path} "
            f"--mesh-quality {mesh_quality} "
            f"--shapes {shapes_path}"
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

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
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