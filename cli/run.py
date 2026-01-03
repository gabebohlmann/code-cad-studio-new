# cli/run.py

import os
import sys
import shlex
import argparse
import traceback
import json
import math

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
# three-cad-viewer Shapes JSON exporter (protocol v3)
# ----------------------------
def _vec3(v):
    try:
        return (float(v.x), float(v.y), float(v.z))
    except Exception:
        return (float(v[0]), float(v[1]), float(v[2]))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(a):
    n = _norm(a)
    if n <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _bbox_from_vertices_flat(verts_flat):
    xs = verts_flat[0::3]
    ys = verts_flat[1::3]
    zs = verts_flat[2::3]
    return {
        "xmin": float(min(xs, default=0.0)),
        "xmax": float(max(xs, default=0.0)),
        "ymin": float(min(ys, default=0.0)),
        "ymax": float(max(ys, default=0.0)),
        "zmin": float(min(zs, default=0.0)),
        "zmax": float(max(zs, default=0.0)),
    }


def _export_three_cad_viewer_shapes_json(doc, out_path: str, quality: str):
    out_path = _normalize_path(out_path)

    shape = _gather_target_shape(doc)
    if shape is None:
        return False, "Shapes JSON not created (no Part shapes in document)"

    q = (quality or "preview").lower().strip()

    # Keep consistent with your STL preview/final intent.
    if q == "final":
        linear_defl = 0.05
        edge_defl = 0.20
    else:
        linear_defl = 0.30
        edge_defl = 0.80

    # ---- Triangles
    # We duplicate vertices per triangle so normals can stay sharp (no smoothing across faces).
    verts_flat = []
    norms_flat = []
    tris_flat = []

    try:
        pts, facets = shape.tessellate(float(linear_defl))
        pts = [_vec3(p) for p in pts]

        vidx = 0
        for f in facets:
            idxs = list(f)
            if len(idxs) < 3:
                continue

            # fan triangulation if polygon
            for t in range(1, len(idxs) - 1):
                p0 = pts[idxs[0]]
                p1 = pts[idxs[t]]
                p2 = pts[idxs[t + 1]]

                n = _normalize(_cross(_sub(p1, p0), _sub(p2, p0)))

                verts_flat.extend(
                    [
                        p0[0],
                        p0[1],
                        p0[2],
                        p1[0],
                        p1[1],
                        p1[2],
                        p2[0],
                        p2[1],
                        p2[2],
                    ]
                )
                norms_flat.extend([n[0], n[1], n[2]] * 3)
                tris_flat.extend([vidx, vidx + 1, vidx + 2])
                vidx += 3

    except Exception as e:
        return False, f"Shapes tessellation failed: {e}"

    # ---- Edges (flattened as segments)
    edges_flat = []
    try:
        for e in getattr(shape, "Edges", []) or []:
            try:
                pts_e = e.discretize(Deflection=float(edge_defl))
                pts_e = [_vec3(p) for p in pts_e]
                for i in range(len(pts_e) - 1):
                    a = pts_e[i]
                    b = pts_e[i + 1]
                    edges_flat.extend([a[0], a[1], a[2], b[0], b[1], b[2]])
            except Exception:
                continue
    except Exception:
        pass

    bb = _bbox_from_vertices_flat(verts_flat)

    # Protocol v3 expects loc as [[x,y,z],[qx,qy,qz,qw]] (not a flat list)
    ident_loc = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]]

    shapes = {
        "version": 3,
        "parts": [
            {
                "id": "/Group/Part_0",
                "type": "shapes",
                "subtype": "solid",
                "name": "Part_0",
                "shape": {
                    "vertices": verts_flat,
                    "triangles": tris_flat,
                    "normals": norms_flat,
                    "edges": edges_flat,
                },
                "state": [1, 1],
                "color": "#cccccc",
                "alpha": 1.0,
                "texture": None,
                "loc": ident_loc,
                "renderback": False,
                "accuracy": None,
                "bb": None,
            }
        ],
        "loc": ident_loc,
        "name": "Group",
        "id": "/Group",
        "normal_len": 0,
        "bb": bb,
    }

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(shapes, f)
        return True, f"Exported Shapes JSON ({q}): {out_path}"
    except Exception as e:
        return False, f"Shapes JSON save failed: {e}"


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
    parser.add_argument("--shapes", required=False, help="Optional Shapes JSON output path (.json)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    mod_root = _add_mod_root_to_syspath()

    code_path = _normalize_path(args.code)
    out_path = _normalize_path(args.out) if args.out else None
    mesh_path = _normalize_path(args.mesh) if args.mesh else None
    shapes_path = _normalize_path(args.shapes) if args.shapes else None

    if args.verbose:
        _log(f"[CodeCADStudio] mod_root={mod_root}")
        _log(f"[CodeCADStudio] code={code_path}")
        _log(f"[CodeCADStudio] out ={out_path}")
        _log(f"[CodeCADStudio] mesh={mesh_path}")
        _log(f"[CodeCADStudio] shapes={shapes_path}")
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

        if shapes_path:
            ok, msg = _export_three_cad_viewer_shapes_json(doc, shapes_path, args.mesh_quality)
            _log("[CodeCADStudio] " + msg)
            if not ok:
                return 8

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