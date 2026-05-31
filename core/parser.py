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


def _extract_balanced_call_at_start(expr: str, func_name: str) -> tuple[str | None, str]:
    """
    Extract `Func(...)` from the beginning of expr.

    Returns:
        (arg_string, remaining_text_after_call)
    """
    s = expr.strip()
    prefix = func_name + "("
    if not s.startswith(prefix):
        return None, expr

    start = len(func_name)
    depth = 0
    for i, ch in enumerate(s[start:], start=start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                arg_str = s[start + 1 : i]
                rest = s[i + 1 :].strip()
                return arg_str, rest

    return None, expr


def _find_top_level_boolean_operator(rhs: str) -> tuple[str | None, str | None, str | None]:
    """
    Split a RHS expression on a top-level boolean operator.

    Supported:
        left + right
        left - right
        left & right

    Ignores operators inside function calls, tuples, etc.
    """
    depth = 0

    for i, ch in enumerate(rhs):
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            continue

        if depth != 0 or ch not in ["+", "-", "&"]:
            continue

        # Avoid treating unary minus as boolean subtraction.
        if ch == "-":
            prev = rhs[:i].rstrip()
            if not prev or prev[-1] in "([,+-*&=":
                continue

        left = rhs[:i].strip()
        right = rhs[i + 1 :].strip()
        if left and right:
            return ch, left, right

    return None, None, None


def _parse_placed_primitive_expr(expr: str, local_env: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse a simple primitive expression, optionally preceded by Pos(...)*.

    Supported examples:
        Box(10, 10, 10)
        Cylinder(radius=3, height=10)
        Pos(5, 0, 0) * Cylinder(radius=3, height=10)
    """
    s = expr.strip()
    pos_vec = None

    if s.startswith("Pos("):
        pos_args, rest = _extract_balanced_call_at_start(s, "Pos")
        if pos_args is None:
            return None

        parts = _split_args(pos_args)
        if len(parts) >= 3:
            x = resolve_value(parts[0], local_env)
            y = resolve_value(parts[1], local_env)
            z = resolve_value(parts[2], local_env)
            if x is not None and y is not None and z is not None:
                pos_vec = FreeCAD.Base.Vector(float(x), float(y), float(z))

        rest = rest.strip()
        if rest.startswith("*"):
            s = rest[1:].strip()
        else:
            return None

    for prim in ["Box", "Cylinder", "Sphere", "Cone", "Torus"]:
        arg_str, rest = _extract_balanced_call_at_start(s, prim)
        if arg_str is not None and rest.strip() == "":
            pos, kw = _parse_args_kwargs(arg_str)
            return {
                "prim": (prim, pos, kw),
                "pos": pos_vec,
            }

    return None


def _extract_boolean_expr(line: str, local_env: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract a simple two-input boolean expression from a `part = ...` line.

    Supported:
        part = Primitive(...) + Primitive(...)
        part = Primitive(...) - Primitive(...)
        part = Primitive(...) & Primitive(...)
        part = Primitive(...) - Pos(...) * Primitive(...)
    """
    stripped = line.strip()
    if not stripped.startswith("part") or "=" not in stripped:
        return None

    lhs, rhs = stripped.split("=", 1)
    if lhs.strip() != "part":
        return None

    op, left, right = _find_top_level_boolean_operator(rhs)
    if op is None:
        return None

    left_info = _parse_placed_primitive_expr(left, local_env)
    right_info = _parse_placed_primitive_expr(right, local_env)

    if left_info is None or right_info is None:
        return None

    return {
        "op": op,
        "left": left_info,
        "right": right_info,
    }


def _boolean_type_id(op: str) -> str:
    if op == "+":
        return "Part::Fuse"
    if op == "-":
        return "Part::Cut"
    if op == "&":
        return "Part::Common"
    raise ValueError(f"Unsupported boolean op: {op}")

def _ensure_codecad_managed_boolean(obj: Any) -> None:
    """
    Mark a boolean object as CodeCAD-managed.
    """
    if not hasattr(obj, "CodeCAD_ManagedBoolean"):
        try:
            obj.addProperty(
                "App::PropertyBool",
                "CodeCAD_ManagedBoolean",
                "CodeCAD",
                "If true, this boolean was created/managed by CodeCAD code sync.",
            )
        except Exception:
            pass

    try:
        obj.CodeCAD_ManagedBoolean = True
    except Exception:
        pass

def _new_block() -> dict[str, Any]:
    """
    Create a parser block.

    A block may contain:
    - one primitive
    - one boolean expression
    - zero or more modifiers
    - optional Pos transform
    """
    return {"prim": None, "bool": None, "mods": [], "pos": None}


def _extract_modifier_call(line: str, local_env: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extracts a supported modifier call from a line of build123d code.

    Supported for native FreeCAD sync:
      part = fillet(part.edges(), radius=...)
      part = chamfer(part.edges(), length=...)

    Returns a modifier dict or None.
    """
    if "part" not in line or "=" not in line:
        return None

    for mod_type in ("fillet", "chamfer"):
        arg_str = _extract_call(line, mod_type)
        if arg_str is None:
            continue

        pos, kw = _parse_args_kwargs(arg_str)
        selector = pos[0].strip() if pos else ""

        return {
            "type": mod_type,
            "selector": selector,
            "pos_args": pos,
            "kwargs": kw,
            "name": None,
        }

    return None


def _selector_is_all_edges(selector: str) -> bool:
    """
    Returns True when a build123d selector maps cleanly to all FreeCAD edges.

    This keeps the first native modifier sync intentionally conservative.
    """
    compact = re.sub(r"\s+", "", selector or "")
    return compact == "part.edges()"


def _resolve_modifier_value(mod: dict[str, Any], local_env: dict[str, Any]) -> float | None:
    """
    Resolves the numeric radius/length value for fillet/chamfer.
    """
    mod_type = mod["type"]
    pos_args = mod.get("pos_args", [])
    kw = mod.get("kwargs", {})

    if mod_type == "fillet":
        if "radius" in kw:
            return resolve_value(kw["radius"], local_env)
        if len(pos_args) > 1:
            return resolve_value(pos_args[1], local_env)
        return None

    if mod_type == "chamfer":
        for key in ("length", "size", "distance"):
            if key in kw:
                return resolve_value(kw[key], local_env)
        if len(pos_args) > 1:
            return resolve_value(pos_args[1], local_env)
        return None

    return None


def _modifier_type_id(mod_type: str) -> str:
    """
    Maps build123d modifier names to FreeCAD Part feature TypeIds.
    """
    return "Part::Fillet" if mod_type == "fillet" else "Part::Chamfer"


def _modifier_default_name(base_name: str, mod_type: str, index: int) -> str:
    """
    Produces stable names for code-created modifiers.
    """
    title = "Fillet" if mod_type == "fillet" else "Chamfer"
    return f"{base_name}_{title}{index}"


def _ensure_codecad_managed_modifier(obj: Any) -> None:
    """
    Marks a modifier as managed by CodeCAD's code->FreeCAD parser.

    This allows us to remove stale code-created modifiers later without deleting
    unrelated hand-created FreeCAD GUI modifiers.
    """
    if not hasattr(obj, "CodeCAD_ManagedModifier"):
        try:
            obj.addProperty(
                "App::PropertyBool",
                "CodeCAD_ManagedModifier",
                "CodeCAD",
                "If true, this modifier was created/managed by CodeCAD code sync.",
            )
        except Exception:
            pass

    try:
        obj.CodeCAD_ManagedModifier = True
    except Exception:
        pass


def _is_codecad_managed_modifier(obj: Any) -> bool:
    """
    Returns True if this object is a CodeCAD-managed modifier.
    """
    try:
        return bool(getattr(obj, "CodeCAD_ManagedModifier", False))
    except Exception:
        return False


def _get_or_create_modifier(doc, name: str, mod_type: str) -> tuple[Any | None, bool, str | None]:
    """
    Gets or creates a native FreeCAD Part::Fillet / Part::Chamfer object.
    """
    desired_type = _modifier_type_id(mod_type)
    obj = doc.getObject(name)

    if obj and getattr(obj, "TypeId", None) != desired_type:
        return None, False, f"Object named {name} exists but is {obj.TypeId}, not {desired_type}"

    created = False
    if not obj:
        obj = doc.addObject(desired_type, name)
        created = True

    _ensure_codecad_managed_modifier(obj)
    return obj, created, None


def _current_base(obj: Any) -> Any | None:
    """
    Returns the actual base object from a modifier Base property.
    """
    base = getattr(obj, "Base", None)
    if isinstance(base, tuple):
        return base[0]
    return base


def _edge_tuples_for_all_edges(base_obj: Any, value: float) -> list[tuple[int, float, float]]:
    """
    Builds the FreeCAD Edges tuple list for all edges on a base object.

    Part::Fillet and Part::Chamfer both use edge tuples shaped like:
      (edge_index, value1, value2)
    """
    try:
        FreeCAD.ActiveDocument.recompute()
    except Exception:
        pass

    shape = getattr(base_obj, "Shape", None)
    edges = list(getattr(shape, "Edges", []) or [])
    return [(i + 1, float(value), float(value)) for i in range(len(edges))]

def _set_object_visible(obj: Any, visible: bool) -> None:
    """
    Sets object visibility without importing FreeCADGui.

    FreeCAD GUI modifier commands usually hide the base object and show the
    resulting modifier object. CodeCAD-created native modifiers should mimic
    that behavior so the base shape is not overlaid with the modified result.
    """
    if obj is None:
        return

    try:
        obj.Visibility = bool(visible)
    except Exception:
        pass

    try:
        if hasattr(obj, "ViewObject") and obj.ViewObject:
            obj.ViewObject.Visibility = bool(visible)
    except Exception:
        pass


def _apply_native_modifier(
    doc,
    base_obj: Any,
    mod: dict[str, Any],
    base_name: str,
    index: int,
    local_env: dict[str, Any],
) -> tuple[Any, bool, str | None]:
    """
    Applies one build123d modifier line as a native FreeCAD modifier object.

    Returns:
      (new_chain_tip, changed, error_message)
    """
    mod_type = mod["type"]
    selector = mod.get("selector", "")

    # Keep this first version conservative. Unsupported selectors stay shadow-only.
    if not _selector_is_all_edges(selector):
        return base_obj, False, None

    value = _resolve_modifier_value(mod, local_env)
    if value is None:
        return base_obj, False, f"Could not resolve {mod_type} value"

    if value <= 0:
        return base_obj, False, f"{mod_type} value must be greater than zero"

    mod_name = mod.get("name") or _modifier_default_name(base_name, mod_type, index)
    mod_obj, created, err = _get_or_create_modifier(doc, mod_name, mod_type)
    if err:
        return base_obj, False, err

    changed = bool(created)

    if _current_base(mod_obj) is not base_obj:
        mod_obj.Base = base_obj
        changed = True
    
    # Match FreeCAD GUI feature-chain display behavior:
    # hide the input/base object and show the modifier result.
    _set_object_visible(base_obj, False)
    _set_object_visible(mod_obj, True)

    new_edges = _edge_tuples_for_all_edges(base_obj, value)
    if not new_edges:
        return base_obj, changed, f"No edges found for {mod_type} base object"

    try:
        old_edges = list(getattr(mod_obj, "Edges", []) or [])
    except Exception:
        old_edges = []

    if old_edges != new_edges:
        mod_obj.Edges = new_edges
        changed = True

    try:
        mod_obj.touch()
    except Exception:
        pass

    return mod_obj, changed, None


def _remove_stale_codecad_modifiers(doc, keep_names: set[str]) -> bool:
    """
    Removes CodeCAD-managed modifiers that no longer exist in the code.

    This prevents old code-created Fillet/Chamfer objects from remaining in the
    feature tree after the user deletes the corresponding line from the editor.
    """
    removed_any = False

    for obj in list(doc.Objects):
        if obj.Name == "Build123d_Shadow":
            continue

        if not _is_codecad_managed_modifier(obj):
            continue

        if obj.Name in keep_names:
            continue

        try:
            base = _current_base(obj)
            _set_object_visible(base, True)
        except Exception:
            pass

        try:
            doc.removeObject(obj.Name)
            removed_any = True
        except Exception:
            pass

    return removed_any

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
    last_prim_name = None

    # For each block, collect the first primitive line, modifier lines,
    # and an optional Pos(...).
    blocks = {}  # name -> {"prim": (...), "mods": [...], "pos": Vector|None}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        m_block = block_pattern.match(line)
        if m_block:
            current_name = m_block.group(1)
            if current_name not in blocks:
                blocks[current_name] = _new_block()
            continue

        if not current_name:
            current_name = "CodePart"
            if current_name not in blocks:
                blocks[current_name] = _new_block()

        # Boolean detection must happen before primitive detection.
        # Otherwise `part = Box(...) - Cylinder(...)` gets mistaken for just Box.
        bool_info = _extract_boolean_expr(line, local_env)
        if bool_info is not None:
            base_name = f"{current_name}_Base"
            tool_name = f"{current_name}_Tool"

            bool_block = blocks.pop(current_name, _new_block())

            blocks[base_name] = _new_block()
            blocks[base_name]["prim"] = bool_info["left"]["prim"]
            blocks[base_name]["pos"] = bool_info["left"]["pos"]

            blocks[tool_name] = _new_block()
            blocks[tool_name]["prim"] = bool_info["right"]["prim"]
            blocks[tool_name]["pos"] = bool_info["right"]["pos"]

            bool_block["bool"] = {
                "op": bool_info["op"],
                "base_name": base_name,
                "tool_name": tool_name,
            }

            blocks[current_name] = bool_block
            continue

        # Primitive detection
        matched_primitive = False
        for prim in ["Box", "Cylinder", "Sphere", "Cone", "Torus"]:
            arg_str = _extract_call(line, prim)
            if arg_str is not None and "part" in line and "=" in line:
                pos, kw = _parse_args_kwargs(arg_str)
                blocks[current_name]["prim"] = (prim, pos, kw)
                last_prim_name = current_name
                matched_primitive = True
                break

        if matched_primitive:
            continue

        # Modifier detection.
        #
        # Supports both:
        #   # Box
        #   part = Box(...)
        #   part = fillet(part.edges(), radius=1.0)
        #
        # and transpiler-style:
        #   # Box
        #   part = Box(...)
        #
        #   # Fillet
        #   part = fillet(part.edges(), radius=1.0)
        mod = _extract_modifier_call(line, local_env)
        if mod is not None:
            target_name = current_name

            # If this is a modifier-only block like "# Fillet", attach it to
            # the most recent primitive block but preserve the FreeCAD object
            # name from the header.
            if blocks[current_name]["prim"] is None and last_prim_name:
                target_name = last_prim_name
                mod["name"] = current_name

            if target_name in blocks:
                blocks[target_name]["mods"].append(mod)

            continue

        # Transform detection.
        # If Pos appears in a modifier-only block, apply it to the most recent
        # primitive root so the whole FreeCAD chain moves together.
        if "Pos(" in line and "* part" in line:
            v = _parse_pos_transform(line, local_env)
            if v is not None:
                target_name = current_name
                if blocks[current_name]["prim"] is None and last_prim_name:
                    target_name = last_prim_name
                blocks[target_name]["pos"] = v

    if not blocks:
        return True, "No Changes"

    existing_part_objs = [
        o for o in doc.Objects if o.Name != "Build123d_Shadow" and o.TypeId.startswith("Part::")
    ]
    code_first = (len(existing_part_objs) == 0)

    changes_made = False
    origin_refresh_list = []

    for name, info in blocks.items():
        prim = info.get("prim")
        bool_info = info.get("bool")

        if prim is None and bool_info is None:
            continue

        # Boolean feature path:
        #   part = Box(...) + Cylinder(...)
        #   part = Box(...) - Cylinder(...)
        #   part = Box(...) & Cylinder(...)
        #
        # Boolean detection creates hidden primitive input blocks first:
        #   <name>_Base
        #   <name>_Tool
        #
        # Then this block creates the visible native FreeCAD boolean object:
        #   Part::Fuse / Part::Cut / Part::Common
        if bool_info is not None:
            base_obj = doc.getObject(bool_info["base_name"])
            tool_obj = doc.getObject(bool_info["tool_name"])

            if base_obj is None or tool_obj is None:
                return False, "Boolean inputs were not created"

            desired_type = _boolean_type_id(bool_info["op"])
            obj = doc.getObject(name)

            created = False
            changed_this_obj = False

            if obj and getattr(obj, "TypeId", None) != desired_type:
                doc.removeObject(obj.Name)
                obj = None

            if not obj:
                obj = doc.addObject(desired_type, name)
                created = True
                changed_this_obj = True

            _ensure_codecad_managed_boolean(obj)

            if getattr(obj, "Base", None) is not base_obj:
                obj.Base = base_obj
                changed_this_obj = True

            if getattr(obj, "Tool", None) is not tool_obj:
                obj.Tool = tool_obj
                changed_this_obj = True

            # Match FreeCAD GUI feature-chain display behavior:
            # inputs are hidden, result is shown.
            _set_object_visible(base_obj, False)
            _set_object_visible(tool_obj, False)
            _set_object_visible(obj, True)

            try:
                obj.touch()
            except Exception:
                pass

            # Allow modifier lines after a boolean, e.g.
            #   part = Box(...) - Cylinder(...)
            #   part = fillet(part.edges(), radius=1.0)
            chain_tip = obj
            for mod_index, mod in enumerate(info.get("mods", []), start=1):
                chain_tip, mod_changed, err = _apply_native_modifier(
                    doc=doc,
                    base_obj=chain_tip,
                    mod=mod,
                    base_name=name,
                    index=mod_index,
                    local_env=local_env,
                )

                if err:
                    return False, err

                if mod_changed:
                    changes_made = True

            if created or changed_this_obj:
                changes_made = True

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

        chain_tip = obj
        for mod_index, mod in enumerate(info.get("mods", []), start=1):
            chain_tip, mod_changed, err = _apply_native_modifier(
                doc=doc,
                base_obj=chain_tip,
                mod=mod,
                base_name=name,
                index=mod_index,
                local_env=local_env,
            )

            if err:
                return False, err

            if mod_changed:
                changes_made = True
        
        if not info.get("mods"):
            _set_object_visible(obj, True)

        if created or changed_this_obj:
            changes_made = True

    keep_modifier_names = set()
    for base_name, info in blocks.items():
        if info.get("prim") is None and info.get("bool") is None:
            continue

        for mod_index, mod in enumerate(info.get("mods", []), start=1):
            keep_modifier_names.add(
                mod.get("name") or _modifier_default_name(base_name, mod["type"], mod_index)
            )

    if _remove_stale_codecad_modifiers(doc, keep_modifier_names):
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