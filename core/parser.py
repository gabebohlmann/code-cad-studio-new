# core/parser.py

import FreeCAD
import FreeCAD as App
import re
from typing import Any

def resolve_value(val_str: str, local_env: dict[str, Any]) -> float | None:
    """
    Resolves a string value to a float, checking the local environment for variables.

    Args:
        val_str (str): The string to resolve (e.g., "10.0" or "L").
        local_env (dict[str, Any]): Dictionary of local variables.

    Returns:
        float | None: The resolved float value, or None if unresolvable.
    """
    try:
        return float(val_str)
    except Exception:
        if val_str in local_env:
            try:
                return float(local_env[val_str])
            except Exception:
                pass
    return None


def parse_variables(code: str) -> list[dict[str, float]]:
    """
    Parses code to find primitive calls and updates existing FreeCAD objects.

    Uses regex and AST-like parsing to identify:
    1. Variable definitions.
    2. Object creation calls (Box, Cylinder, etc.).
    3. Pos() transformations.

    Args:
        code (str): The complete Python script.

    Returns:
        list[dict[str, float]]: (Success boolean, Status message).
    """
    vars_found = []
    lines = code.split("\n")
    pattern = re.compile(
        r"""^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:#.*)?$"""
    )
    for idx, line in enumerate(lines):
        match = pattern.match(line.strip())
        if match:
            vars_found.append({"name": match.group(1), "value": float(match.group(2))})
    return vars_found


def _extract_call(line: str, func_name: str) -> str | None:
    """
    Extracts the raw arguments string from a function call line.

    Locates the substring inside the outermost parentheses of a specific function call.

    Args:
        line (str): The line of code to parse.
        func_name (str): The function name to target (e.g., "Box").

    Returns:
        str | None: The content inside the parentheses (e.g., "10, 20, L=5"), 
        or None if the function call is not found.
    """
    i = line.find(func_name + "(")
    if i < 0:
        return None
    s = line[i + len(func_name) + 1 :]
    j = s.rfind(")")
    if j < 0:
        return None 
    return s[:j]


def _split_args(arg_str: str) -> list[str]:
    """
    Splits a raw argument string by commas, respecting parentheses nesting.

    Used to separate arguments while ignoring commas inside tuples or function calls 
    (e.g., `(1, 2), 3` becomes `['(1, 2)', '3']`).

    Args:
        arg_str (str): The raw string between parentheses.

    Returns:
        list[str]: A list of individual argument strings.
    """
    parts = []
    cur = ""
    depth = 0
    for ch in arg_str:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _parse_args_kwargs(arg_str: str) -> tuple[list[str], dict[str, str]]:
    """
    Parses a raw argument string into positional and keyword components.

    Args:
        arg_str (str): The raw string between parentheses.

    Returns:
        tuple[list[str], dict[str, str]]: A tuple containing:
            - list[str]: Positional arguments as raw strings.
            - dict[str, str]: Keyword arguments map (key -> raw value string).
    """
    pos = []
    kw = {}
    for p in _split_args(arg_str):
        if "=" in p:
            k, v = p.split("=", 1)
            kw[k.strip()] = v.strip()
        else:
            pos.append(p)
    return pos, kw


def _ensure_codecad_props(obj: App.DocumentObject) -> None:
    """
    Injects custom Code-CAD properties into a FreeCAD object if missing.

    Adds:
    - `CodeCAD_UseB123dOrigin` (Bool): Tracks if the object is visually centered on Build123d origin or not(FreeCAD origin).
    - `CodeCAD_OriginDelta` (Vector): Stores the world-space offset vector used for alignment.

    Args:
        obj (App.DocumentObject): The FreeCAD object to patch.
    """
    if not hasattr(obj, "CodeCAD_UseB123dOrigin"):
        obj.addProperty(
            "App::PropertyBool",
            "CodeCAD_UseB123dOrigin",
            "CodeCAD",
            "If true, prefer build123d default origin/alignment for generated code.",
        )
        obj.CodeCAD_UseB123dOrigin = False

    if not hasattr(obj, "CodeCAD_OriginDelta"):
        obj.addProperty(
            "App::PropertyVector",
            "CodeCAD_OriginDelta",
            "CodeCAD",
            "World-space delta applied to Placement when enabling build123d origin.",
        )
        obj.CodeCAD_OriginDelta = FreeCAD.Base.Vector(0, 0, 0)



def _bbox_center_local(obj: Any) -> FreeCAD.Base.Vector | None:
    """
    Calculates the center of the object's bounding box in local coordinates.

    For Part:: primitives, `obj.Shape` is defined relative to the object's Placement.
    Therefore, the bounding box center of `obj.Shape` represents the geometric center 
    relative to the object's local origin (0,0,0).

    Args:
        obj (App.DocumentObject): The object to inspect.

    Returns:
        FreeCAD.Base.Vector | None: The center vector, or None if invalid.
    """
    shp = getattr(obj, "Shape", None)
    if not shp:
        return None
    try:
        bb = shp.BoundBox
        if not bb:
            return None
        return bb.Center
    except Exception:
        return None


def _apply_b123d_origin_for_new_object(obj: Any) -> None:
    """
    Aligns a newly created object to match build123d's default origin logic.

    Build123d primitives are typically centered at (0,0,0), whereas FreeCAD primitives 
    are anchored at a corner or base. This function shifts the FreeCAD Placement 
    so the visual geometric center sits at the Placement origin.

    Args:
        obj (App.DocumentObject): The newly created FreeCAD object.
    """
    _ensure_codecad_props(obj)

    # Need a recompute so Shape/BoundBox is valid
    try:
        FreeCAD.ActiveDocument.recompute()
    except Exception:
        pass

    c_local = _bbox_center_local(obj)
    if c_local is None:
        obj.CodeCAD_UseB123dOrigin = True
        obj.CodeCAD_OriginDelta = FreeCAD.Base.Vector(0, 0, 0)
        return

    # world delta (respect rotation)
    try:
        rot = obj.Placement.Rotation
        delta_world = rot.multVec(c_local)
    except Exception:
        delta_world = c_local

    # shift so bbox center becomes origin
    obj.Placement.Base = obj.Placement.Base.sub(delta_world)
    obj.CodeCAD_UseB123dOrigin = True
    obj.CodeCAD_OriginDelta = delta_world


def _refresh_b123d_origin_after_param_change(obj: Any) -> bool:
    """
    Recalculates alignment shift after object parameters (dimensions) change.

    If dimensions change (e.g., a Box grows from 10 to 20), the center point shifts 
    relative to the corner. This function:
    1. Undoes the previous shift (restores corner alignment).
    2. Recomputes geometry to get the new bounding box.
    3. Calculates the new center offset.
    4. Re-applies the shift.

    Args:
        obj (App.DocumentObject): The object to update.

    Returns:
        bool: True if an update was performed, False if the object is not in 
        build123d-origin mode or failed to update.
    """
    _ensure_codecad_props(obj)

    if not bool(getattr(obj, "CodeCAD_UseB123dOrigin", False)):
        return False

    old_delta = getattr(obj, "CodeCAD_OriginDelta", FreeCAD.Base.Vector(0, 0, 0))

    # 1) undo previous shift
    try:
        obj.Placement.Base = obj.Placement.Base.add(old_delta)
    except Exception:
        return False

    # 2) recompute so bbox updates
    try:
        FreeCAD.ActiveDocument.recompute()
    except Exception:
        pass

    c_local = _bbox_center_local(obj)
    if c_local is None:
        obj.CodeCAD_OriginDelta = FreeCAD.Base.Vector(0, 0, 0)
        return True

    # 3) compute new delta in world space
    try:
        rot = obj.Placement.Rotation
        new_delta = rot.multVec(c_local)
    except Exception:
        new_delta = c_local

    # 4) apply updated shift
    try:
        obj.Placement.Base = obj.Placement.Base.sub(new_delta)
        obj.CodeCAD_OriginDelta = new_delta
        obj.CodeCAD_UseB123dOrigin = True
        return True
    except Exception:
        return False


def _parse_pos_transform(line: str, local_env: dict[str, Any]) -> FreeCAD.Base.Vector | None:
    """
    Parses a `Pos(x, y, z)` transformation from a line of code.

    Expected format matches regex: `Pos(...)`.

    Args:
        line (str): The line of code containing the transformation.
        local_env (dict): Dictionary used to resolve variable names to values.

    Returns:
        FreeCAD.Base.Vector | None: The translation vector, or None if not found/invalid.
    """
    m = re.search(r"Pos\s*\(\s*([^\)]+)\)", line)
    if not m:
        return None
    inside = m.group(1)
    parts = _split_args(inside)
    if len(parts) < 3:
        return None
    x = resolve_value(parts[0], local_env)
    y = resolve_value(parts[1], local_env)
    z = resolve_value(parts[2], local_env)
    if x is None or y is None or z is None:
        return None
    return FreeCAD.Base.Vector(float(x), float(y), float(z))


def inject_code_to_freecad(full_code: str) -> tuple[bool, str]:
    """
    Parses code to find primitive calls and updates existing FreeCAD objects.

    Uses regex and AST-like parsing to identify:
    1. Variable definitions.
    2. Object creation calls (Box, Cylinder, etc.).
    3. Pos() transformations.

    Args:
        full_code (str): The complete Python script.

    Returns:
        tuple[bool, str]: (Success boolean, Status message).
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        return False, "No Document"

    try:
        compile(full_code, "<string>", "exec")
    except SyntaxError:
        return False, "Syntax Error"

    # Evaluate variables/constants for numeric extraction
    local_env = {}
    try:
        exec("from build123d import *", local_env)
        exec(full_code, local_env)
    except Exception as e:
        return False, f"Runtime Error: {e}"

    # Identify blocks (# Name)
    block_pattern = re.compile(r"^#\s*(\w+)", re.MULTILINE)

    lines = full_code.split("\n")
    current_name = None

    # For each block, collect the first primitive line + an optional following Pos(...)
    blocks = {}  # name -> {"prim": (type, posargs, kwargs), "pos": Vector|None}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        m_block = block_pattern.match(line)
        if m_block:
            current_name = m_block.group(1)
            if current_name not in blocks:
                blocks[current_name] = {"prim": None, "pos": None}
            continue

        if not current_name:
            current_name = "CodePart"
            if current_name not in blocks:
                blocks[current_name] = {"prim": None, "pos": None}

        # Primitive detection
        for prim in ["Box", "Cylinder", "Sphere", "Cone", "Torus"]:
            arg_str = _extract_call(line, prim)
            if arg_str is not None and "part" in line and "=" in line:
                pos, kw = _parse_args_kwargs(arg_str)
                blocks[current_name]["prim"] = (prim, pos, kw)
                break

        # Transform detection
        if "Pos(" in line and "* part" in line:
            v = _parse_pos_transform(line, local_env)
            if v is not None:
                blocks[current_name]["pos"] = v

    if not blocks:
        return True, "No Changes"

    existing_part_objs = [
        o for o in doc.Objects if o.Name != "Build123d_Shadow" and o.TypeId.startswith("Part::")
    ]
    code_first = (len(existing_part_objs) == 0)

    changes_made = False
    origin_refresh_list = []

    for name, info in blocks.items():
        prim = info["prim"]
        if prim is None:
            continue

        prim_type, pos_args, kw = prim
        pos_vec = info["pos"]

        obj = doc.getObject(name)

        # Create object if missing
        created = False
        if not obj:
            created = True
            if prim_type == "Box":
                obj = doc.addObject("Part::Box", name)
            elif prim_type == "Cylinder":
                obj = doc.addObject("Part::Cylinder", name)
            elif prim_type == "Sphere":
                obj = doc.addObject("Part::Sphere", name)
            elif prim_type == "Cone":
                obj = doc.addObject("Part::Cone", name)
            elif prim_type == "Torus":
                obj = doc.addObject("Part::Torus", name)
            else:
                continue

        def gv(key, default=None):
            if key in kw:
                return resolve_value(kw[key], local_env)
            return default

        changed_this_obj = False

        # Box
        if obj.TypeId == "Part::Box" and prim_type == "Box":
            l = resolve_value(pos_args[0], local_env) if len(pos_args) > 0 else gv("length")
            w = resolve_value(pos_args[1], local_env) if len(pos_args) > 1 else gv("width")
            h = resolve_value(pos_args[2], local_env) if len(pos_args) > 2 else gv("height")
            if l is not None and abs(obj.Length.Value - l) > 1e-6:
                obj.Length.Value = l
                changed_this_obj = True
            if w is not None and abs(obj.Width.Value - w) > 1e-6:
                obj.Width.Value = w
                changed_this_obj = True
            if h is not None and abs(obj.Height.Value - h) > 1e-6:
                obj.Height.Value = h
                changed_this_obj = True

        # Cylinder
        elif obj.TypeId == "Part::Cylinder" and prim_type == "Cylinder":
            r = gv("radius", None)
            if r is None and len(pos_args) > 0:
                r = resolve_value(pos_args[0], local_env)
            hh = gv("height", None)
            if hh is None and len(pos_args) > 1:
                hh = resolve_value(pos_args[1], local_env)

            if r is not None and abs(obj.Radius.Value - r) > 1e-6:
                obj.Radius.Value = r
                changed_this_obj = True
            if hh is not None and abs(obj.Height.Value - hh) > 1e-6:
                obj.Height.Value = hh
                changed_this_obj = True

        # Sphere
        elif obj.TypeId == "Part::Sphere" and prim_type == "Sphere":
            r = gv("radius", None)
            if r is None and len(pos_args) > 0:
                r = resolve_value(pos_args[0], local_env)

            a1 = gv("arc_size1", None)
            a2 = gv("arc_size2", None)
            a3 = gv("arc_size3", None)

            if r is not None and abs(obj.Radius.Value - r) > 1e-6:
                obj.Radius.Value = r
                changed_this_obj = True

            if a1 is not None and abs(float(getattr(obj, "Angle1", -90.0)) - float(a1)) > 1e-6:
                obj.Angle1 = float(a1)
                changed_this_obj = True
            if a2 is not None and abs(float(getattr(obj, "Angle2", 90.0)) - float(a2)) > 1e-6:
                obj.Angle2 = float(a2)
                changed_this_obj = True
            if a3 is not None and abs(float(getattr(obj, "Angle3", 360.0)) - float(a3)) > 1e-6:
                obj.Angle3 = float(a3)
                changed_this_obj = True

        # Cone
        elif obj.TypeId == "Part::Cone" and prim_type == "Cone":
            br = gv("bottom_radius", None)
            tr = gv("top_radius", None)
            hh = gv("height", None)
            ang = gv("arc_size", None)

            if br is None and len(pos_args) > 0:
                br = resolve_value(pos_args[0], local_env)
            if tr is None and len(pos_args) > 1:
                tr = resolve_value(pos_args[1], local_env)
            if hh is None and len(pos_args) > 2:
                hh = resolve_value(pos_args[2], local_env)
            if ang is None and len(pos_args) > 3:
                ang = resolve_value(pos_args[3], local_env)

            if br is not None and abs(obj.Radius1.Value - br) > 1e-6:
                obj.Radius1.Value = br
                changed_this_obj = True
            if tr is not None and abs(obj.Radius2.Value - tr) > 1e-6:
                obj.Radius2.Value = tr
                changed_this_obj = True
            if hh is not None and abs(obj.Height.Value - hh) > 1e-6:
                obj.Height.Value = hh
                changed_this_obj = True
            if ang is not None and abs(float(getattr(obj, "Angle", 360.0)) - float(ang)) > 1e-6:
                obj.Angle = float(ang)
                changed_this_obj = True

        # Torus
        elif obj.TypeId == "Part::Torus" and prim_type == "Torus":
            mr = gv("major_radius", None)
            nr = gv("minor_radius", None)

            if mr is None and len(pos_args) > 0:
                mr = resolve_value(pos_args[0], local_env)
            if nr is None and len(pos_args) > 1:
                nr = resolve_value(pos_args[1], local_env)

            ms = gv("minor_start_angle", None)
            me = gv("minor_end_angle", None)
            ma = gv("major_angle", None)

            if mr is not None and abs(obj.Radius1.Value - mr) > 1e-6:
                obj.Radius1.Value = mr
                changed_this_obj = True
            if nr is not None and abs(obj.Radius2.Value - nr) > 1e-6:
                obj.Radius2.Value = nr
                changed_this_obj = True

            if ms is not None and abs(float(getattr(obj, "Angle1", 0.0)) - float(ms)) > 1e-6:
                obj.Angle1 = float(ms)
                changed_this_obj = True
            if me is not None and abs(float(getattr(obj, "Angle2", 360.0)) - float(me)) > 1e-6:
                obj.Angle2 = float(me)
                changed_this_obj = True
            if ma is not None and abs(float(getattr(obj, "Angle3", 360.0)) - float(ma)) > 1e-6:
                obj.Angle3 = float(ma)
                changed_this_obj = True

        # Placement translation if present
        if pos_vec is not None and hasattr(obj, "Placement"):
            if obj.Placement.Base.distanceToPoint(pos_vec) > 1e-6:
                obj.Placement.Base = pos_vec
                changed_this_obj = True

        # If created in code-first mode, default to build123d origin
        if created and code_first:
            _apply_b123d_origin_for_new_object(obj)
            changed_this_obj = True

        _ensure_codecad_props(obj)
        if (
            bool(getattr(obj, "CodeCAD_UseB123dOrigin", False))
            and changed_this_obj
            and pos_vec is None
        ):
            origin_refresh_list.append(obj)

        if created or changed_this_obj:
            changes_made = True

    if changes_made:
        try:
            doc.recompute()
        except Exception:
            pass

        refreshed_any = False
        for obj in origin_refresh_list:
            if _refresh_b123d_origin_after_param_change(obj):
                refreshed_any = True

        if refreshed_any:
            try:
                doc.recompute()
            except Exception:
                pass

        return True, "Synced"
    
    return True, "No Changes"