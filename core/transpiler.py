# core/transpiler.py

import FreeCAD

def fingerprint(edge):
    try:
        mid = edge.valueAt(edge.Length / 2.0)
        return (round(edge.Length, 4), round(mid.x, 3), round(mid.y, 3), round(mid.z, 3))
    except:
        return None


def _safe_center(geo_shape):
    """
    Robustly get a point-like center for Vertex/Edge/Face objects returned by FreeCAD.
    - Part.Vertex often has .Point (but may not have CenterOfMass reliably)
    - Part.Shape of ShapeType 'Vertex' may expose Vertexes[0].Point
    """
    # 1) Direct vertex point (common for Part.Vertex)
    if hasattr(geo_shape, "Point"):
        try:
            return geo_shape.Point
        except:
            pass

    # 2) CenterOfMass (common for Edge/Face/Solid)
    if hasattr(geo_shape, "CenterOfMass"):
        try:
            return geo_shape.CenterOfMass
        except:
            pass

    # 3) If it's a Part.Shape wrapper with Vertexes list
    if hasattr(geo_shape, "Vertexes"):
        try:
            if geo_shape.Vertexes and hasattr(geo_shape.Vertexes[0], "Point"):
                return geo_shape.Vertexes[0].Point
        except:
            pass

    # 4) Fallback to bounding box center
    if hasattr(geo_shape, "BoundBox"):
        try:
            return geo_shape.BoundBox.Center
        except:
            pass

    return None


def solve_selector(geo_shape):
    """
    Return a build123d selector string for a FreeCAD subshape.
    Supports: Vertex, Edge, Face. Returns None for Compound/unsupported.

    NOTE: Vertex selection previously failed because some FreeCAD vertex objects
    don't provide CenterOfMass reliably; we now use .Point / Vertexes[0].Point.
    """
    try:
        # Some subobjects can be returned as None
        if not geo_shape:
            return None

        # Compounds are ambiguous for selector generation
        if getattr(geo_shape, "ShapeType", None) == "Compound":
            return None

        st = getattr(geo_shape, "ShapeType", None)
        c = _safe_center(geo_shape)
        if c is None:
            return None

        cx, cy, cz = round(c.x, 2), round(c.y, 2), round(c.z, 2)

        if st == "Vertex":
            return f"part.vertices().sort_by_distance(({cx}, {cy}, {cz})).first"

        if st == "Edge":
            return f"part.edges().sort_by_distance(({cx}, {cy}, {cz})).first"

        if st == "Face":
            # Prefer axis-aligned face selectors when possible
            try:
                n = geo_shape.normalAt(0, 0)
                if abs(n.z) > 0.99:
                    return f"part.faces().sort_by(Axis.Z).{'last' if c.z > 0 else 'first'}"
                if abs(n.x) > 0.99:
                    return f"part.faces().sort_by(Axis.X).{'last' if c.x > 0 else 'first'}"
                if abs(n.y) > 0.99:
                    return f"part.faces().sort_by(Axis.Y).{'last' if c.y > 0 else 'first'}"
            except:
                pass
            return f"part.faces().sort_by_distance(({cx}, {cy}, {cz})).first"

        # Unsupported ShapeType (Wire/Solid/etc.) for now
        return None

    except:
        return None


def generate_smart_selector_code(selected_geoms, parent_obj):
    if not selected_geoms:
        return ["part.edges()"]

    sel_prints = set()
    for g in selected_geoms:
        fp = fingerprint(g)
        if fp:
            sel_prints.add(fp)

    if not sel_prints:
        return ["part.edges()"]

    total_edges = parent_obj.Shape.Edges
    if len(sel_prints) == len(total_edges):
        return ["part.edges()"]

    candidates = []

    for face in parent_obj.Shape.Faces:
        f_prints = {fingerprint(e) for e in face.Edges}
        sel_code = solve_selector(face)
        if sel_code:
            candidates.append((f_prints, f"{sel_code}.edges()"))

    for axis, axis_name in [
        (FreeCAD.Base.Vector(1, 0, 0), "Axis.X"),
        (FreeCAD.Base.Vector(0, 1, 0), "Axis.Y"),
        (FreeCAD.Base.Vector(0, 0, 1), "Axis.Z"),
    ]:
        a_prints = set()
        for e in total_edges:
            try:
                if abs(e.tangentAt(e.Length / 2.0).dot(axis)) > 0.99:
                    a_prints.add(fingerprint(e))
            except:
                pass
        if a_prints:
            candidates.append((a_prints, f"part.edges().filter_by({axis_name})"))

    for prints, code in candidates:
        if sel_prints == prints:
            return [code]

    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if sel_prints == candidates[i][0].union(candidates[j][0]):
                return [candidates[i][1], candidates[j][1]]

    selectors = []
    for g in selected_geoms:
        code = solve_selector(g)
        if code:
            selectors.append(code)

    return selectors


def get_geometry_from_links(obj, parent):
    geoms = []
    names = []

    if hasattr(obj, "EdgeLinks") and isinstance(obj.EdgeLinks, tuple) and len(obj.EdgeLinks) > 1:
        names = obj.EdgeLinks[1]
    elif isinstance(obj.Base, tuple):
        names = obj.Base[1]

    for name in names:
        g = parent.getSubObject(name)
        if g:
            if g.ShapeType == "Compound":
                geoms.extend(g.Edges)
            else:
                geoms.append(g)

    return geoms


def transpile_object(obj):
    header = f"# {obj.Name}\n"

    if obj.TypeId == "Part::Box":
        l, w, h = obj.Length.Value, obj.Width.Value, obj.Height.Value
        return f"{header}part = Box({l}, {w}, {h}, align=(Align.MIN, Align.MIN, Align.MIN))"

    elif obj.TypeId == "Part::Cylinder":
        r, h = obj.Radius.Value, obj.Height.Value
        return f"{header}part = Cylinder(radius={r}, height={h}, align=(Align.CENTER, Align.CENTER, Align.MIN))"

    elif obj.TypeId in ["Part::Fillet", "Part::Chamfer"]:
        parent = None
        if hasattr(obj, "Base"):
            parent = obj.Base
        if isinstance(parent, tuple):
            parent = parent[0]
        if not parent:
            return "# Error: Orphaned Modifier"

        parent_code = transpile_object(parent)
        selected_geoms = get_geometry_from_links(obj, parent)
        selectors = generate_smart_selector_code(selected_geoms, parent)
        combined = " + ".join(selectors)

        if len(selectors) > 1 and "part.edges" not in combined:
            combined = f"({combined})"

        val = 1.0
        if hasattr(obj, "Edges") and obj.Edges:
            try:
                val = obj.Edges[0][1]
            except:
                pass
        elif hasattr(obj, "Radius"):
            val = obj.Radius.Value
        elif hasattr(obj, "Size"):
            val = obj.Size.Value

        op = "fillet" if obj.TypeId == "Part::Fillet" else "chamfer"
        param = "radius" if op == "fillet" else "length"
        return f"{parent_code}\n\n{header}part = {op}({combined}, {param}={val})"

    return f"# Unsupported Object: {obj.TypeId}"