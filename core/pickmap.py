# core/pickmap.py

from __future__ import annotations

import hashlib
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


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

    # The current CodeCAD result should usually be the final listed object.
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

    candidates = []
    try:
        objects = list(doc.Objects)
    except Exception:
        return None

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


def build_pickmap(
    *,
    doc: Any,
    code: str,
    ir_doc: dict[str, Any] | None = None,
    render_part_id: str = "/Group/Part_0",
    render_part_name: str = "Part_0",
    export_source: str = "shapes_json",
) -> dict[str, Any]:
    """
    Build a viewer-neutral selection map for the current render artifact.

    MVP scope:
      - object-level selection only
      - maps the rendered three-cad-viewer Part_0 to the best CodeCAD/FreeCAD object
      - later versions will add face/edge/triangle maps
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
    shape_summary = None

    if ir_obj:
        object_id = str(ir_obj.get("id") or ir_obj.get("name") or "Part_0")
        object_name = str(ir_obj.get("name") or object_id)
        root_feature = ir_obj.get("root")

    if doc_obj is not None:
        freecad_name = getattr(doc_obj, "Name", None)
        freecad_label = getattr(doc_obj, "Label", None)
        object_type = getattr(doc_obj, "TypeId", None)
        shape_summary = _shape_summary_from_obj(doc_obj)

        if object_id is None:
            object_id = str(freecad_name or render_part_name)
        if object_name is None:
            object_name = str(freecad_label or freecad_name or object_id)

    if object_id is None:
        object_id = render_part_name
    if object_name is None:
        object_name = object_id
    if object_type is None:
        object_type = "unknown"
    if shape_summary is None:
        shape_summary = {
            "has_shape": False,
            "vertices": 0,
            "edges": 0,
            "faces": 0,
            "solids": 0,
            "volume": 0.0,
            "area": 0.0,
            "bbox": None,
        }

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
                    object_name,
                    object_id,
                ],
                "faces": [],
                "edges": [],
                "vertices": [],
            }
        ],
    }
