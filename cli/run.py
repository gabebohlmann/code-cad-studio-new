# cli/run.py

import os
import sys
import shlex
import argparse
import traceback

import FreeCAD


# ----------------------------
# Logging: stdout + optional log file
# ----------------------------
_LOG_FH = None

def _linebuf():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass


def _init_log_file():
    """
    If CODECAD_LOG is set (server sets it), also log to that file.
    This helps even when stdout capture is flaky.
    """
    global _LOG_FH
    try:
        p = os.environ.get("CODECAD_LOG", "").strip()
        if p:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _LOG_FH = open(p, "a", encoding="utf-8")
            _LOG_FH.write("=== run.py start ===\n")
            _LOG_FH.flush()
    except Exception:
        _LOG_FH = None


def _log(msg: str):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        if _LOG_FH:
            _LOG_FH.write(msg + "\n")
            _LOG_FH.flush()
    except Exception:
        pass


def _normalize_path(p: str) -> str:
    return os.path.abspath(p).replace("\\", "/")


# ----------------------------
# argv handling (robust for FreeCADCmd weirdness)
# ----------------------------
def _massage_argv(raw):
    """
    Handles several shapes of sys.argv coming from FreeCADCmd.

    Common patterns:
      1) script args arrive normally: ['--code', 'X', '--mesh', 'Y']
      2) everything after --pass is one string: ['--code X --mesh Y --verbose']
      3) FreeCAD leaves '--pass' in argv: ['--pass', '--code X --mesh Y ...'] or ['--pass', '_', ...]
      4) placeholder '_' shows up
    """
    if not raw:
        return raw

    # If FreeCAD leaves "--pass" in argv, take everything after it.
    if "--pass" in raw:
        i = raw.index("--pass")
        raw = raw[i + 1 :]

    # Drop placeholder '_' if present
    if raw and raw[0] in ("_", "--", "PASS", "pass"):
        raw = raw[1:]

    # If it all came through as one string, split it like a shell would
    if len(raw) == 1 and isinstance(raw[0], str):
        s = raw[0].strip()

        # Strip one layer of wrapping quotes around the whole string if present
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1].strip()

        # On Windows, posix=False behaves more like cmd/powershell quoting
        try:
            raw = shlex.split(s, posix=(os.name != "nt"))
        except Exception:
            raw = s.split()

    return raw


def _add_mod_root_to_syspath():
    mod_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if mod_root not in sys.path:
        sys.path.insert(0, mod_root)
    return mod_root


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ----------------------------
# Exports
# ----------------------------
def _export_step(doc, out_path: str):
    out_path = _normalize_path(out_path)
    try:
        import Import
        Import.export(doc.Objects, out_path)
        return True, f"Exported STEP: {out_path}"
    except Exception as e1:
        try:
            import ImportGui
            ImportGui.export(doc.Objects, out_path)
            return True, f"Exported STEP via ImportGui: {out_path}"
        except Exception as e2:
            return False, f"STEP export failed: {e1} / {e2}"


def _export_fcstd(doc, out_path: str):
    out_path = _normalize_path(out_path)
    try:
        doc.saveAs(out_path)
        return True, f"Saved FCStd: {out_path}"
    except Exception as e:
        return False, f"FCStd save failed: {e}"


def _gather_target_shape(doc):
    """
    Return a Part.Shape to mesh/export:
    - Prefer engine tip object if possible
    - else compound all non-shadow Part:: shapes
    """
    try:
        from core.engine import SyncEngine
        from core.freecad_api import FreeCADAPI

        engine = SyncEngine(FreeCADAPI())
        tip = engine.find_tip_object(doc)
        if tip and getattr(tip, "Shape", None) and not tip.Shape.isNull():
            return tip.Shape
    except Exception:
        pass

    shapes = []
    for obj in doc.Objects:
        if obj.Name == "Build123d_Shadow":
            continue
        if not getattr(obj, "TypeId", "").startswith("Part::"):
            continue
        shp = getattr(obj, "Shape", None)
        if shp and (not shp.isNull()):
            shapes.append(shp)

    if not shapes:
        return None

    try:
        import Part
        return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    except Exception:
        return shapes[0]


def _export_mesh_stl(doc, out_path: str, quality: str):
    out_path = _normalize_path(out_path)

    shape = _gather_target_shape(doc)
    if shape is None:
        return False, "Mesh not created (no Part shapes in document)"

    try:
        import MeshPart

        q = (quality or "preview").lower().strip()
        if q == "final":
            linear_defl = 0.05
            angular_defl = 0.15
        else:
            linear_defl = 0.30
            angular_defl = 0.45

        mesh = MeshPart.meshFromShape(
            Shape=shape,
            LinearDeflection=float(linear_defl),
            AngularDeflection=float(angular_defl),
            Relative=True,
        )
        mesh.write(out_path)
        return True, f"Exported STL ({q}): {out_path}"
    except Exception as e:
        return False, f"STL export failed: {e}"


# ----------------------------
# Main
# ----------------------------
def main(argv=None):
    _linebuf()
    _init_log_file()

    _log(f"[CodeCADStudio] run.py loaded")
    _log(f"[CodeCADStudio] sys.argv={sys.argv}")

    argv = sys.argv[1:] if argv is None else argv
    argv = _massage_argv(list(argv))

    _log(f"[CodeCADStudio] argv(after massage)={argv}")

    parser = argparse.ArgumentParser(prog="code-cad-studio")
    parser.add_argument("--code", required=True, help="Path to build123d python file")
    parser.add_argument("--out", required=False, help="Output .FCStd or .step/.stp path")
    parser.add_argument("--mesh", required=False, help="Optional STL output path (.stl)")
    parser.add_argument("--mesh-quality", required=False, default="preview", choices=["preview", "final"])
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    mod_root = _add_mod_root_to_syspath()

    code_path = _normalize_path(args.code)
    out_path = _normalize_path(args.out) if args.out else None
    mesh_path = _normalize_path(args.mesh) if args.mesh else None

    if args.verbose:
        _log(f"[CodeCADStudio] mod_root={mod_root}")
        _log(f"[CodeCADStudio] code={code_path}")
        _log(f"[CodeCADStudio] out ={out_path}")
        _log(f"[CodeCADStudio] mesh={mesh_path}")
        _log(f"[CodeCADStudio] mesh_quality={args.mesh_quality}")

    if not os.path.exists(code_path):
        _log(f"[CodeCADStudio] ERROR: code file not found: {code_path}")
        return 2

    try:
        from core.engine import SyncEngine
        from core.freecad_api import FreeCADAPI
    except Exception:
        _log("[CodeCADStudio] ERROR: failed to import core.* (sys.path issue?)")
        traceback.print_exc()
        return 3

    doc = FreeCAD.newDocument("CodeCADStudio_CLI")
    FreeCAD.setActiveDocument(doc.Name)

    engine = SyncEngine(FreeCADAPI())

    try:
        code = _read_text(code_path)

        result = engine.apply_pipeline(code, make_shadow=True, verify=False)
        if not result.get("ok", False):
            _log("[CodeCADStudio] APPLY FAILED: " + str(result.get("message")))
            return 4

        _log("[CodeCADStudio] APPLY OK: " + str(result.get("message")))

        try:
            doc.recompute()
        except Exception:
            pass

        if out_path:
            low = out_path.lower()
            if low.endswith(".fcstd"):
                ok, msg = _export_fcstd(doc, out_path)
                _log("[CodeCADStudio] " + msg)
                if not ok:
                    return 5
            elif low.endswith((".step", ".stp")):
                ok, msg = _export_step(doc, out_path)
                _log("[CodeCADStudio] " + msg)
                if not ok:
                    return 6
            else:
                _log("[CodeCADStudio] WARNING: --out extension not recognized (use .FCStd or .step/.stp)")

        if mesh_path:
            ok, msg = _export_mesh_stl(doc, mesh_path, args.mesh_quality)
            _log("[CodeCADStudio] " + msg)
            if not ok:
                return 7

        return 0

    except SystemExit:
        raise
    except Exception:
        _log("[CodeCADStudio] ERROR: unhandled exception")
        traceback.print_exc()
        return 10
    finally:
        try:
            doc.recompute()
        except Exception:
            pass
        try:
            if _LOG_FH:
                _LOG_FH.write("=== run.py end ===\n")
                _LOG_FH.flush()
        except Exception:
            pass


# IMPORTANT: FreeCAD sometimes executes scripts in ways where __name__ may not be "__main__".
# Calling main() unconditionally here makes CLI behavior deterministic when FreeCADCmd "processes" run.py.
try:
    rc = main()
except SystemExit as e:
    rc = int(getattr(e, "code", 1) or 1)
except Exception:
    traceback.print_exc()
    rc = 10

try:
    sys.exit(rc)
except Exception:
    pass