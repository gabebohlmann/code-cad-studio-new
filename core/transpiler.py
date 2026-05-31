# core/transpiler.py

import FreeCAD


def fingerprint(edge):
    """
    Creates a unique signature for an edge based on length and midpoint.

    Args:
        edge (TopoDS_Edge): The edge to fingerprint.

    Returns:
        tuple | None: (Length, mid_x, mid_y, mid_z) or None on error.
    """
    try:
        mid = edge.valueAt(edge.Length / 2.0)
        return (round(edge.Length, 4), round(mid.x, 3), round(mid.y, 3), round(mid.z, 3))
    except Exception:
        return None


def _safe_center(geo_shape):
    """
    Robustly attempts to find a center point for a generic topological shape.

    Different FreeCAD shapes (Vertex, Edge, Face, Solid) expose their position 
    or center of mass via different attributes. This function tries them in order:
    1. `.Point` (Vertex)
    2. `.CenterOfMass` (Edge, Face, Solid)
    3. First Vertex's Point (Fallback)
    4. Bounding Box Center (Fallback)

    Args:
        geo_shape (TopoDS_Shape): The FreeCAD geometry object to inspect.

    Returns:
        FreeCAD.Base.Vector | None: The center vector, or None if undetermined.
    """
    if hasattr(geo_shape, "Point"):
        try:
            return geo_shape.Point
        except Exception:
            pass

    if hasattr(geo_shape, "CenterOfMass"):
        try:
            return geo_shape.CenterOfMass
        except Exception:
            pass

    if hasattr(geo_shape, "Vertexes"):
        try:
            if geo_shape.Vertexes and hasattr(geo_shape.Vertexes[0], "Point"):
                return geo_shape.Vertexes[0].Point
        except Exception:
            pass

    if hasattr(geo_shape, "BoundBox"):
        try:
            return geo_shape.BoundBox.Center
        except Exception:
            pass

    return None


def solve_selector(geo_shape):
    """
    Generates a build123d selector string for a specific sub-shape.

    Analyzes the shape's geometric properties (center, normal) to generate 
    stable selection code.

    Logic:
    - **Vertices/Edges:** Selects the nearest entity to the shape's center 
      (e.g., `part.edges().sort_by_distance((x,y,z)).first`).
    - **Planar Faces:** If aligned with X/Y/Z axes, uses `sort_by(Axis.X)` 
      with `.first` or `.last` based on position.
    - **Curved/Angled Faces:** Fallback to `sort_by_distance`.

    Args:
        geo_shape (TopoDS_Shape): The sub-shape (Face, Edge, Vertex) to target.

    Returns:
        str | None: The Python code snippet (e.g., `"part.faces().sort_by(Axis.Z).last"`),
        or None if the shape is complex/compound.
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
            except Exception:
                pass
            return f"part.faces().sort_by_distance(({cx}, {cy}, {cz})).first"

        return None

    except Exception:
        return None


def generate_smart_selector_code(selected_geoms, parent_obj):
    """
    Generates build123d selector code (e.g., `part.faces().sort_by(...)`) 
    for a given set of selected sub-shapes.

    Args:
        selected_geoms (list): List of selected FreeCAD shape objects.
        parent_obj (object): The parent FreeCAD object (e.g., a Box).

    Returns:
        list[str]: A list of selector strings.
    """
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
            except Exception:
                pass
        if a_prints:
            candidates.append((a_prints, f"part.edges().sort_by({axis_name})"))

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
    """
    Retrieves the actual topological sub-shapes referenced by a modifier object.

    FreeCAD modifiers (like Fillet/Chamfer) store references to the edges/faces 
    they modify in properties like `EdgeLinks` or `Base` (as tuple). 
    This function parses those names and fetches the geometry from the parent.

    Args:
        obj (App.DocumentObject): The modifier object (e.g., Part::Fillet).
        parent (App.DocumentObject): The base object being modified (e.g., Part::Box).

    Returns:
        list[TopoDS_Shape]: A list of edges or faces to be operated on.
    """
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


def _use_b123d_origin(obj) -> bool:
    """
    Checks if the object is flagged to use build123d origin logic.

    Args:
        obj (object): The FreeCAD object.

    Returns:
        bool: True if the property 'CodeCAD_UseB123dOrigin' is set.
    """
    try:
        return bool(getattr(obj, "CodeCAD_UseB123dOrigin", False))
    except Exception:
        return False


def _bbox_center_local(obj):
    """
    Calculates the center of the object's bounding box in local coordinates.

    Note:
        This is a local helper similar to `parser._bbox_center_local`.
        In FreeCAD, `obj.Shape` is typically defined in local space relative 
        to `obj.Placement`. Therefore, `Shape.BoundBox.Center` gives the 
        geometric center relative to the object's local origin.

    Args:
        obj (App.DocumentObject): The object to inspect.

    Returns:
        FreeCAD.Base.Vector | None: The center vector, or None if invalid.
    """
    try:
        shp = getattr(obj, "Shape", None)
        if not shp:
            return None
        bb = shp.BoundBox
        if not bb:
            return None
        return bb.Center
    except Exception:
        return None

def _prop_float(obj, prop_name: str, default: float = 0.0) -> float:
    """
    Reads a FreeCAD property as a float.

    Handles App::PropertyLength / quantity-like values such as `5.0 mm`,
    as well as plain numeric properties.
    """
    try:
        v = obj.getPropertyByName(prop_name)
    except Exception:
        v = getattr(obj, prop_name, default)

    try:
        return float(v.Value)
    except Exception:
        try:
            return float(v)
        except Exception:
            return float(default)


def _is_part_tube(obj) -> bool:
    """
    Detects a FreeCAD Part Workbench Tube.

    FreeCAD's Part Tube is created through BasicShapes.Shapes.addTube().
    It reports as Part::FeaturePython, not Part::Tube, and has:
      - OuterRadius
      - InnerRadius
      - Height
    """
    if not obj:
        return False

    if getattr(obj, "TypeId", "") != "Part::FeaturePython":
        return False

    props = set(getattr(obj, "PropertiesList", []) or [])
    return {"OuterRadius", "InnerRadius", "Height"}.issubset(props)


def _transpile_part_tube(obj, header: str) -> str:
    """
    Converts a FreeCAD Part Tube to native build123d algebra-mode code.

    build123d has no Tube primitive, so we emit the equivalent:
      outer cylinder - inner cylinder
    """
    outer = _prop_float(obj, "OuterRadius", 5.0)
    inner = _prop_float(obj, "InnerRadius", 2.0)
    height = _prop_float(obj, "Height", 10.0)

    if outer <= 0:
        return f"{header}# Error: Tube outer radius must be greater than zero"
    if inner < 0:
        return f"{header}# Error: Tube inner radius must be zero or greater"
    if inner >= outer:
        return f"{header}# Error: Tube inner radius must be smaller than outer radius"
    if height <= 0:
        return f"{header}# Error: Tube height must be greater than zero"

    # FreeCAD Part Tube bottom face lies on the XY plane with center at origin.
    # That corresponds to build123d Z-min alignment for cylinders.
    if _use_b123d_origin(obj):
        align_arg = ""
    else:
        align_arg = ", align=(Align.CENTER, Align.CENTER, Align.MIN)"

    return (
        f"{header}"
        f"outer = Cylinder(radius={outer}, height={height}{align_arg})\n"
        f"inner = Cylinder(radius={inner}, height={height}{align_arg})\n"
        "part = outer - inner"
    )

def transpile_object(obj):
    """
    Converts a FreeCAD object into its build123d Python representation.

    Args:
        obj (object): The FreeCAD object (e.g., Part::Box).

    Returns:
        str: The generated Python code string.
    """
    header = f"# {obj.Name}\n"

    if _is_part_tube(obj):
        return _transpile_part_tube(obj, header)

    if obj.TypeId == "Part::Box":
        l, w, h = obj.Length.Value, obj.Width.Value, obj.Height.Value
        if _use_b123d_origin(obj):
            return f"{header}part = Box({l}, {w}, {h})"
        return f"{header}part = Box({l}, {w}, {h}, align=(Align.MIN, Align.MIN, Align.MIN))"

    elif obj.TypeId == "Part::Cylinder":
        r, h = obj.Radius.Value, obj.Height.Value
        if _use_b123d_origin(obj):
            return f"{header}part = Cylinder(radius={r}, height={h})"
        return f"{header}part = Cylinder(radius={r}, height={h}, align=(Align.CENTER, Align.CENTER, Align.MIN))"

    elif obj.TypeId == "Part::Cone":
        r1 = float(getattr(obj, "Radius1", 5.0))
        r2 = float(getattr(obj, "Radius2", 2.0))
        h = float(getattr(obj, "Height", 10.0))
        ang = float(getattr(obj, "Angle", 360.0))

        def _is_default(v, d):
            try:
                return abs(float(v) - float(d)) < 1e-9
            except Exception:
                return False

        is_full = _is_default(ang, 360.0)

        if _use_b123d_origin(obj):
            if is_full:
                return f"{header}part = Cone(bottom_radius={r1}, top_radius={r2}, height={h})"
            return f"{header}part = Cone(bottom_radius={r1}, top_radius={r2}, height={h}, arc_size={ang})"

        if is_full:
            return f"{header}part = Cone(bottom_radius={r1}, top_radius={r2}, height={h}, align=(Align.CENTER, Align.CENTER, Align.MIN))"
        return f"{header}part = Cone(bottom_radius={r1}, top_radius={r2}, height={h}, arc_size={ang}, align=(Align.CENTER, Align.CENTER, Align.MIN))"

    elif obj.TypeId == "Part::Sphere":
        r = obj.Radius.Value
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
            return f"{header}part = Sphere(radius={r})"

        lines = []
        lines.append(f"{header}part = Sphere(radius={r}, arc_size1={a1}, arc_size2={a2}, arc_size3={a3})")

        if not _use_b123d_origin(obj):
            c_local = _bbox_center_local(obj)
            if c_local is not None:
                cx, cy, cz = float(c_local.x), float(c_local.y), float(c_local.z)
                if abs(cx) > 1e-9 or abs(cy) > 1e-9 or abs(cz) > 1e-9:
                    lines.append(f"part = Pos({cx:.6f}, {cy:.6f}, {cz:.6f}) * part")

        return "\n".join(lines)

    elif obj.TypeId == "Part::Torus":
        R1 = float(getattr(obj, "Radius1", 10.0))  # major
        R2 = float(getattr(obj, "Radius2", 2.0))   # minor

        a1 = float(getattr(obj, "Angle1", 0.0))     # minor start
        a2 = float(getattr(obj, "Angle2", 360.0))   # minor end
        a3 = float(getattr(obj, "Angle3", 360.0))   # major revolve

        def _is_default(v, d):
            try:
                return abs(float(v) - float(d)) < 1e-9
            except Exception:
                return False

        is_full = _is_default(a1, 0.0) and _is_default(a2, 360.0) and _is_default(a3, 360.0)

        if is_full:
            return f"{header}part = Torus(major_radius={R1}, minor_radius={R2})"

        args = [f"major_radius={R1}", f"minor_radius={R2}"]
        if not _is_default(a1, 0.0):
            args.append(f"minor_start_angle={a1}")
        if not _is_default(a2, 360.0):
            args.append(f"minor_end_angle={a2}")
        if not _is_default(a3, 360.0):
            args.append(f"major_angle={a3}")

        lines = [f"{header}part = Torus({', '.join(args)})"]

        if not _use_b123d_origin(obj):
            c_local = _bbox_center_local(obj)
            if c_local is not None:
                cx, cy, cz = float(c_local.x), float(c_local.y), float(c_local.z)
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
        # OLD: selectors not working well, need to analyze geometry to generate better ones
        selected_geoms = get_geometry_from_links(obj, parent)
        selectors = generate_smart_selector_code(selected_geoms, parent)
        combined = " + ".join(selectors)

        if len(selectors) > 1 and "part.edges" not in combined:
            combined = f"({combined})"

        val = 1.0
        if hasattr(obj, "Edges") and obj.Edges:
            try:
                val = obj.Edges[0][1]
            except Exception:
                pass
        elif hasattr(obj, "Radius"):
            val = obj.Radius.Value
        elif hasattr(obj, "Size"):
            val = obj.Size.Value

        op = "fillet" if obj.TypeId == "Part::Fillet" else "chamfer"
        param = "radius" if op == "fillet" else "length"
        return f"{parent_code}\n\n{header}part = {op}({combined}, {param}={val})"

    return f"# Unsupported Object: {obj.TypeId}"