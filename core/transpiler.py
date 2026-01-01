# core/transpiler.py

import FreeCAD
import math


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
    if hasattr(geo_shape, "Point"):
        try:
            return geo_shape.Point
        except:
            pass

    if hasattr(geo_shape, "CenterOfMass"):
        try:
            return geo_shape.CenterOfMass
        except:
            pass

    if hasattr(geo_shape, "Vertexes"):
        try:
            if geo_shape.Vertexes and hasattr(geo_shape.Vertexes[0], "Point"):
                return geo_shape.Vertexes[0].Point
        except:
            pass

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
    """
    try:
        if not geo_shape:
            return None

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


# -----------------------------------------------------------------------------
# Sphere offset correction
# -----------------------------------------------------------------------------
def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _partial_sphere_bbox_center(radius, a1_deg, a2_deg, a3_deg):
    """
    Approximate bounding box center (in sphere-center coordinates) for a FreeCAD-like
    clipped sphere:
      - latitude range [a1, a2] where -90..90
      - revolution about Z from 0 .. a3 (degrees)

    This is intentionally consistent with "sphere centered at origin",
    which is what FreeCAD does for Part::Sphere.

    We use:
      zmin = r*sin(a1), zmax = r*sin(a2)
      xy radius max = r*cos(lat0) where lat0 is clamped 0 inside [a1,a2]
      sector angles = [0, a3] (normalized)
      bbox extremes in xy from sector endpoints plus quadrant angles inside.
    """
    r = float(radius)

    # Normalize latitude ordering
    a1 = float(a1_deg)
    a2 = float(a2_deg)
    if a2 < a1:
        a1, a2 = a2, a1

    # Z bounds from latitude
    zmin = r * math.sin(math.radians(a1))
    zmax = r * math.sin(math.radians(a2))
    cz = 0.5 * (zmin + zmax)

    # Handle full revolution => symmetric in XY
    theta = float(a3_deg)

    # Normalize theta into [0, 360] while preserving "full" if >= 360
    if abs(theta) >= 360.0:
        return (0.0, 0.0, cz)

    # Clamp lat0 to closest-to-equator latitude to maximize XY radius
    lat0 = _clamp(0.0, a1, a2)
    rho = r * math.cos(math.radians(lat0))

    # If the band doesn't include any meaningful XY radius
    if abs(rho) < 1e-12:
        return (0.0, 0.0, cz)

    # Consider sector angles from 0..theta (allow negative theta)
    start = 0.0
    end = theta
    if end < start:
        start, end = end, start

    # Candidate angles (deg): endpoints + quadrant angles within [start,end]
    candidates = [start, end]
    for q in [0.0, 90.0, 180.0, 270.0, 360.0]:
        if start - 1e-9 <= q <= end + 1e-9:
            candidates.append(q)

    xs = []
    ys = []
    for ang in candidates:
        a = math.radians(ang)
        xs.append(rho * math.cos(a))
        ys.append(rho * math.sin(a))

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)

    return (cx, cy, cz)


def transpile_object(obj):
    header = f"# {obj.Name}\n"

    if obj.TypeId == "Part::Box":
        l, w, h = obj.Length.Value, obj.Width.Value, obj.Height.Value
        return f"{header}part = Box({l}, {w}, {h}, align=(Align.MIN, Align.MIN, Align.MIN))"

    elif obj.TypeId == "Part::Cylinder":
        r, h = obj.Radius.Value, obj.Height.Value
        return f"{header}part = Cylinder(radius={r}, height={h}, align=(Align.CENTER, Align.CENTER, Align.MIN))"

    elif obj.TypeId == "Part::Sphere":
        r = obj.Radius.Value

        # FreeCAD Part Sphere uses Angle1/Angle2/Angle3 for partial spheres
        a1 = float(getattr(obj, "Angle1", -90.0))
        a2 = float(getattr(obj, "Angle2", 90.0))
        a3 = float(getattr(obj, "Angle3", 360.0))

        def _is_default(v, d):
            try:
                return abs(float(v) - float(d)) < 1e-9
            except Exception:
                return False

        is_full = _is_default(a1, -90.0) and _is_default(a2, 90.0) and _is_default(a3, 360.0)

        if is_full:
            return f"{header}part = Sphere(radius={r}, align=(Align.CENTER, Align.CENTER, Align.CENTER))"

        # Build the clipped sphere
        lines = []
        lines.append(
            f"{header}part = Sphere(radius={r}, arc_size1={a1}, arc_size2={a2}, arc_size3={a3}, "
            f"align=(Align.CENTER, Align.CENTER, Align.CENTER))"
        )

        # ✅ Correct build123d bbox-centering so the sphere center stays at origin like FreeCAD
        cx, cy, cz = _partial_sphere_bbox_center(r, a1, a2, a3)

        # Only emit if meaningful
        if abs(cx) > 1e-9 or abs(cy) > 1e-9 or abs(cz) > 1e-9:
            lines.append(f"part = Pos({cx:.6f}, {cy:.6f}, {cz:.6f}) * part")

        return "\n".join(lines)

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