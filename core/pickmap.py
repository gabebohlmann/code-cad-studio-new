# core/pickmap.py

from __future__ import annotations

import hashlib
import math
import re
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _vec3(v: Any) -> tuple[float, float, float]:
    try:
        return (float(v.x), float(v.y), float(v.z))
    except Exception:
        try:
            return (float(v[0]), float(v[1]), float(v[2]))
        except Exception:
            return (0.0, 0.0, 0.0)


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


def _bbox_from_points(points: list[tuple[float, float, float]]) -> dict[str, Any] | None:
    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]

    return {
        "xmin": float(min(xs)),
        "xmax": float(max(xs)),
        "ymin": float(min(ys)),
        "ymax": float(max(ys)),
        "zmin": float(min(zs)),
        "zmax": float(max(zs)),
        "center": [
            float((min(xs) + max(xs)) / 2.0),
            float((min(ys) + max(ys)) / 2.0),
            float((min(zs) + max(zs)) / 2.0),
        ],
    }


def _shape_summary_from_shape(shape: Any) -> dict[str, Any]:
    if shape is None:
        return {
            "has_shape": False,
            "vertices": 0,
            "edges": 0,
            "faces": 0,
            "solids": 0,
            "volume": 0.0,
            "area": 0.0,
            "bbox": None,
        }

    try:
        is_null = bool(shape.isNull())
    except Exception:
        is_null = False

    if is_null:
        return {
            "has_shape": False,
            "vertices": 0,
            "edges": 0,
            "faces": 0,
            "solids": 0,
            "volume": 0.0,
            "area": 0.0,
            "bbox": None,
        }

    bbox = None
    try:
        bb = shape.BoundBox
        bbox = {
            "xmin": _safe_float(bb.XMin),
            "xmax": _safe_float(bb.XMax),
            "ymin": _safe_float(bb.YMin),
            "ymax": _safe_float(bb.YMax),
            "zmin": _safe_float(bb.ZMin),
            "zmax": _safe_float(bb.ZMax),
            "center": [
                _safe_float(bb.Center.x),
                _safe_float(bb.Center.y),
                _safe_float(bb.Center.z),
            ],
        }
    except Exception:
        pass

    return {
        "has_shape": True,
        "vertices": len(getattr(shape, "Vertexes", []) or []),
        "edges": len(getattr(shape, "Edges", []) or []),
        "faces": len(getattr(shape, "Faces", []) or []),
        "solids": len(getattr(shape, "Solids", []) or []),
        "volume": _safe_float(getattr(shape, "Volume", 0.0)),
        "area": _safe_float(getattr(shape, "Area", 0.0)),
        "bbox": bbox,
    }


def _shape_summary_from_obj(obj: Any) -> dict[str, Any]:
    return _shape_summary_from_shape(getattr(obj, "Shape", None))


def _best_ir_object(ir_doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ir_doc:
        return None

    objects = ir_doc.get("objects") or []
    if not objects:
        return None

    try:
        return objects[-1]
    except Exception:
        return None


def _find_doc_object_for_ir(doc: Any, ir_obj: dict[str, Any] | None) -> Any | None:
    if doc is None or not ir_obj:
        return None

    for key in ("name", "id"):
        name = ir_obj.get(key)
        if not name:
            continue

        try:
            obj = doc.getObject(str(name))
            if obj:
                return obj
        except Exception:
            pass

    return None


def _find_best_visible_part_object(doc: Any) -> Any | None:
    """
    Best-effort fallback when IR is unavailable.

    Prefer visible terminal-ish Part objects over hidden boolean inputs.
    """
    if doc is None:
        return None

    try:
        objects = list(doc.Objects)
    except Exception:
        return None

    candidates = []

    for obj in objects:
        name = getattr(obj, "Name", "")
        type_id = getattr(obj, "TypeId", "")

        if name == "Build123d_Shadow":
            continue
        if not type_id.startswith("Part::"):
            continue
        if name.endswith("_Base") or name.endswith("_Tool"):
            continue

        candidates.append(obj)

    if not candidates:
        return None

    visible = []
    for obj in candidates:
        try:
            if bool(getattr(obj, "Visibility", True)):
                visible.append(obj)
        except Exception:
            visible.append(obj)

    return (visible or candidates)[-1]


def _deflection_for_quality(mesh_quality: str | None) -> float:
    q = (mesh_quality or "preview").lower().strip()
    return 0.05 if q == "final" else 0.30


def _surface_type(face: Any) -> str:
    try:
        return type(face.Surface).__name__
    except Exception:
        return "unknown"


def _face_center(face: Any) -> list[float]:
    try:
        c = face.CenterOfMass
        return [_safe_float(c.x), _safe_float(c.y), _safe_float(c.z)]
    except Exception:
        try:
            bb = face.BoundBox
            c = bb.Center
            return [_safe_float(c.x), _safe_float(c.y), _safe_float(c.z)]
        except Exception:
            return [0.0, 0.0, 0.0]


def _tessellate_face(face: Any, deflection: float) -> dict[str, Any]:
    """
    Tessellate one CAD face into a small triangle mesh for browser picking.

    This is separate from the main visual mesh. The browser uses it as a
    transparent hover/click overlay.
    """
    verts_flat: list[float] = []
    tris_flat: list[int] = []
    points_for_bbox: list[tuple[float, float, float]] = []

    try:
        pts, facets = face.tessellate(float(deflection))
        pts = [_vec3(p) for p in pts]

        for p in pts:
            points_for_bbox.append(p)

        for p in pts:
            verts_flat.extend([p[0], p[1], p[2]])

        for facet in facets:
            idxs = list(facet)
            if len(idxs) < 3:
                continue

            # Fan triangulate any polygonal facet.
            for t in range(1, len(idxs) - 1):
                tris_flat.extend([int(idxs[0]), int(idxs[t]), int(idxs[t + 1])])

    except Exception:
        pass

    normal = (0.0, 0.0, 1.0)
    try:
        if len(tris_flat) >= 3 and len(verts_flat) >= 9:
            i0, i1, i2 = tris_flat[0], tris_flat[1], tris_flat[2]
            p0 = (
                verts_flat[3 * i0],
                verts_flat[3 * i0 + 1],
                verts_flat[3 * i0 + 2],
            )
            p1 = (
                verts_flat[3 * i1],
                verts_flat[3 * i1 + 1],
                verts_flat[3 * i1 + 2],
            )
            p2 = (
                verts_flat[3 * i2],
                verts_flat[3 * i2 + 1],
                verts_flat[3 * i2 + 2],
            )
            normal = _normalize(_cross(_sub(p1, p0), _sub(p2, p0)))
    except Exception:
        pass

    return {
        "vertices": verts_flat,
        "triangles": tris_flat,
        "normal": [float(normal[0]), float(normal[1]), float(normal[2])],
        "bbox": _bbox_from_points(points_for_bbox),
    }


def _python_ref_name(name: str | None) -> str:
    """
    Best-effort variable name for selector strings.

    If the object name is not a valid Python identifier, fall back to `part`.
    """
    raw = str(name or "").strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", raw):
        return raw
    return "part"


def _axis_name(axis: str) -> str:
    return {
        "x": "Axis.X",
        "y": "Axis.Y",
        "z": "Axis.Z",
    }[axis]


def _axis_coord(center: list[float], axis: str) -> float:
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    return float(center[idx])


def _add_face_selector_candidates(
    faces: list[dict[str, Any]],
    object_ref: str,
) -> None:
    """
    Add rough build123d selector candidates.

    This is intentionally heuristic. It gives useful early selectors like:
      part.faces().sort_by(Axis.Z)[-1]
    """
    for face in faces:
        face["selector_candidates"] = [
            f"{object_ref}.faces()[{int(face['index']) - 1}]",
        ]

    for axis in ("x", "y", "z"):
        ordered = sorted(
            faces,
            key=lambda f: _axis_coord(f.get("center", [0.0, 0.0, 0.0]), axis),
        )

        for rank, face in enumerate(ordered):
            if len(ordered) == 1:
                idx_expr = "0"
            elif rank == 0:
                idx_expr = "0"
            elif rank == len(ordered) - 1:
                idx_expr = "-1"
            else:
                idx_expr = str(rank)

            face["selector_candidates"].append(
                f"{object_ref}.faces().sort_by({_axis_name(axis)})[{idx_expr}]"
            )


def _build_face_records(
    shape: Any,
    *,
    object_id: str,
    object_ref: str,
    deflection: float,
) -> list[dict[str, Any]]:
    faces: list[dict[str, Any]] = []

    try:
        raw_faces = list(getattr(shape, "Faces", []) or [])
    except Exception:
        raw_faces = []

    for idx, face in enumerate(raw_faces, start=1):
        pick_mesh = _tessellate_face(face, deflection)

        center = _face_center(face)
        area = _safe_float(getattr(face, "Area", 0.0))
        surface_type = _surface_type(face)

        face_id = f"{object_id}.Face{idx}"

        faces.append(
            {
                "face_id": face_id,
                "index": idx,
                "freecad_ref": f"Face{idx}",
                "kind": "face",
                "surface_type": surface_type,
                "center": center,
                "normal": pick_mesh.get("normal", [0.0, 0.0, 1.0]),
                "area": area,
                "bbox": pick_mesh.get("bbox"),
                "pick_mesh": {
                    "vertices": pick_mesh.get("vertices", []),
                    "triangles": pick_mesh.get("triangles", []),
                },
                "selector_candidates": [],
            }
        )

    _add_face_selector_candidates(faces, object_ref)
    return faces


def build_pickmap(
    *,
    doc: Any,
    code: str,
    ir_doc: dict[str, Any] | None = None,
    target_shape: Any | None = None,
    mesh_quality: str | None = "preview",
    render_part_id: str = "/Group/Part_0",
    render_part_name: str = "Part_0",
    export_source: str = "shapes_json",
) -> dict[str, Any]:
    """
    Build a viewer-neutral selection map for the current render artifact.

    v0:
      - object selection
      - face metadata
      - transparent per-face pick meshes for browser hover/click highlighting
    """
    revision = hashlib.sha256((code or "").encode("utf-8")).hexdigest()

    ir_obj = _best_ir_object(ir_doc)
    doc_obj = _find_doc_object_for_ir(doc, ir_obj)
    if doc_obj is None:
        doc_obj = _find_best_visible_part_object(doc)

    object_id = None
    object_name = None
    object_type = None
    freecad_name = None
    freecad_label = None
    root_feature = None

    if ir_obj:
        object_id = str(ir_obj.get("id") or ir_obj.get("name") or "Part_0")
        object_name = str(ir_obj.get("name") or object_id)
        root_feature = ir_obj.get("root")

    if doc_obj is not None:
        freecad_name = getattr(doc_obj, "Name", None)
        freecad_label = getattr(doc_obj, "Label", None)
        object_type = getattr(doc_obj, "TypeId", None)

        if object_id is None:
            object_id = str(freecad_name or render_part_name)
        if object_name is None:
            object_name = str(freecad_label or freecad_name or object_id)

    if object_id is None:
        object_id = render_part_name
    if object_name is None:
        object_name = object_id
    if object_type is None:
        object_type = "Part::Shape"

    shape = target_shape
    if shape is None and doc_obj is not None:
        shape = getattr(doc_obj, "Shape", None)

    shape_summary = _shape_summary_from_shape(shape)
    deflection = _deflection_for_quality(mesh_quality)
    object_ref = _python_ref_name(object_name)

    faces = []
    if shape is not None:
        faces = _build_face_records(
            shape,
            object_id=object_id,
            object_ref=object_ref,
            deflection=deflection,
        )

    return {
        "schema": "codecad.pickmap.v0",
        "render_revision": revision,
        "render_revision_short": revision[:16],
        "export_source": export_source,
        "viewer": {
            "kind": "three-cad-viewer",
            "render_part_id": render_part_id,
            "render_part_name": render_part_name,
        },
        "objects": [
            {
                "object_id": object_id,
                "name": object_name,
                "kind": "object",
                "source": {
                    "freecad_name": freecad_name,
                    "freecad_label": freecad_label,
                    "freecad_type": object_type,
                    "ir_root": root_feature,
                    "render_part_id": render_part_id,
                    "render_part_name": render_part_name,
                },
                "shape": shape_summary,
                "selector_candidates": [
                    object_ref,
                    object_name,
                    object_id,
                ],
                "faces": faces,
                "edges": [],
                "vertices": [],
            }
        ],
    }
