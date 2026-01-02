# core/parser.py

import FreeCAD
import re
import ast


# ----------------------------
# Utilities
# ----------------------------
def resolve_value(val_str, local_env):
    try:
        return float(val_str)
    except Exception:
        if val_str in local_env:
            try:
                return float(local_env[val_str])
            except Exception:
                pass
    return None


def _doc_has_non_shadow_parts(doc):
    if not doc:
        return False
    for o in doc.Objects:
        if o.Name != "Build123d_Shadow" and getattr(o, "TypeId", "").startswith("Part::"):
            return True
    return False


def _make_unique_name(doc, base_name: str) -> str:
    if not doc:
        return base_name
    if not doc.getObject(base_name):
        return base_name
    i = 1
    while doc.getObject(f"{base_name}{i}"):
        i += 1
    return f"{base_name}{i}"


def _ensure_origin_props(obj):
    """Mirror the same per-object properties used by the GUI origin toggle."""
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


def _bbox_center_local(obj):
    """
    bbox center in local coordinates (object space), even with rotation.
    """
    shp = getattr(obj, "Shape", None)
    if not shp:
        return None
    try:
        bb = shp.BoundBox
        c_world = bb.Center
    except Exception:
        return None

    try:
        inv = obj.Placement.inverse()
        return inv.multVec(c_world)
    except Exception:
        try:
            base = obj.Placement.Base
            return FreeCAD.Base.Vector(c_world.x - base.x, c_world.y - base.y, c_world.z - base.z)
        except Exception:
            return None


def _enable_b123d_origin(obj):
    """
    Shift the object so its bbox center becomes local origin, and record delta.
    This makes FreeCAD object "look like" build123d's default origin for primitives.
    """
    _ensure_origin_props(obj)

    try:
        doc = FreeCAD.ActiveDocument
        if doc:
            doc.recompute()
    except Exception:
        pass

    c_local = _bbox_center_local(obj)
    if c_local is None:
        return False

    # Convert local delta to world using placement rotation
    try:
        rot = obj.Placement.Rotation
        delta_world = rot.multVec(c_local)
    except Exception:
        delta_world = c_local

    try:
        obj.Placement.Base = obj.Placement.Base.sub(delta_world)
        obj.CodeCAD_OriginDelta = delta_world
        obj.CodeCAD_UseB123dOrigin = True
        try:
            if FreeCAD.ActiveDocument:
                FreeCAD.ActiveDocument.recompute()
        except Exception:
            pass
        return True
    except Exception:
        return False


def parse_variables(code):
    """Extracts variable names and values from code string."""
    vars_found = []
    lines = code.split("\n")
    pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([-+]?[0-9]*\.?[0-9]+)$")
    for idx, line in enumerate(lines):
        match = pattern.match(line.strip())
        if match:
            vars_found.append({"name": match.group(1), "value": float(match.group(2))})
    return vars_found


# ----------------------------
# AST-based parsing of "part = <Primitive>(...)"
# ----------------------------
def _eval_ast_expr(expr_node, local_env):
    """
    Evaluate a numeric-ish AST expression node using local_env (variables),
    with builtins stripped.
    """
    try:
        compiled = compile(ast.Expression(expr_node), "<ast>", "eval")
        return eval(compiled, {"__builtins__": {}}, local_env)
    except Exception:
        return None


def _extract_first_part_call(full_code, local_env):
    """
    Find the first assignment to `part = <Call>` and return:
      (func_name, args_list, kwargs_dict)
    """
    try:
        tree = ast.parse(full_code)
    except Exception:
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            # targets: [Name('part')]
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "part":
                    if isinstance(node.value, ast.Call):
                        call = node.value
                        func_name = None
                        if isinstance(call.func, ast.Name):
                            func_name = call.func.id
                        elif isinstance(call.func, ast.Attribute):
                            func_name = call.func.attr
                        if not func_name:
                            return None

                        args = [_eval_ast_expr(a, local_env) for a in call.args]
                        kwargs = {}
                        for kw in call.keywords:
                            if kw.arg is None:
                                continue
                            kwargs[kw.arg] = _eval_ast_expr(kw.value, local_env)
                        return func_name, args, kwargs
    return None


def _extract_pos_translation(full_code, local_env):
    """
    Sum translations from patterns like:
      part = Pos(x, y, z) * part
    Returns FreeCAD.Vector or None
    """
    pos_pat = re.compile(r"part\s*=\s*Pos\s*\(\s*([^\)]+)\s*\)\s*\*\s*part")
    total = FreeCAD.Base.Vector(0, 0, 0)

    found_any = False
    for m in pos_pat.finditer(full_code):
        found_any = True
        inside = m.group(1)
        # split by commas
        pieces = [p.strip() for p in inside.split(",")]
        if len(pieces) < 3:
            continue
        x = resolve_value(pieces[0], local_env)
        y = resolve_value(pieces[1], local_env)
        z = resolve_value(pieces[2], local_env)
        if x is None or y is None or z is None:
            continue
        total = total.add(FreeCAD.Base.Vector(float(x), float(y), float(z)))

    return total if found_any else None


# ----------------------------
# Create FreeCAD primitives from build123d calls
# ----------------------------
def _create_freecad_primitive_from_part_call(doc, obj_name, func_name, args, kwargs):
    """
    Create a Part::* object equivalent to build123d primitive call.
    Returns (obj, message) or (None, error_message)
    """
    func = func_name

    # Helper: pull either positional or keyword
    def get_kw_or_pos(key, pos_idx, default=None):
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]
        if pos_idx is not None and pos_idx < len(args) and args[pos_idx] is not None:
            return args[pos_idx]
        return default

    # BOX: Box(length, width, height, ...)
    if func == "Box":
        l = get_kw_or_pos("length", 0, None)
        w = get_kw_or_pos("width", 1, None)
        h = get_kw_or_pos("height", 2, None)
        if l is None or w is None or h is None:
            return None, "Cannot create Box (missing dims)"

        obj = doc.addObject("Part::Box", obj_name)
        obj.Length = float(l)
        obj.Width = float(w)
        obj.Height = float(h)
        return obj, "Created Box"

    # CYLINDER: Cylinder(radius=..., height=...)
    if func == "Cylinder":
        r = get_kw_or_pos("radius", 0, None)
        h = get_kw_or_pos("height", 1, None)
        if r is None or h is None:
            return None, "Cannot create Cylinder (missing radius/height)"

        obj = doc.addObject("Part::Cylinder", obj_name)
        obj.Radius = float(r)
        obj.Height = float(h)
        return obj, "Created Cylinder"

    # SPHERE: Sphere(radius=..., arc_size1=..., arc_size2=..., arc_size3=...)
    if func == "Sphere":
        r = get_kw_or_pos("radius", 0, None)
        if r is None:
            return None, "Cannot create Sphere (missing radius)"

        a1 = get_kw_or_pos("arc_size1", None, None)
        a2 = get_kw_or_pos("arc_size2", None, None)
        a3 = get_kw_or_pos("arc_size3", None, None)

        obj = doc.addObject("Part::Sphere", obj_name)
        obj.Radius = float(r)

        # Only set angles if any provided (otherwise keep FreeCAD defaults)
        if a1 is not None:
            obj.Angle1 = float(a1)
        if a2 is not None:
            obj.Angle2 = float(a2)
        if a3 is not None:
            obj.Angle3 = float(a3)

        return obj, "Created Sphere"

    # CONE: Cone(bottom_radius=..., top_radius=..., height=..., arc_size=...)
    if func == "Cone":
        br = get_kw_or_pos("bottom_radius", 0, None)
        tr = get_kw_or_pos("top_radius", 1, None)
        h = get_kw_or_pos("height", 2, None)
        ang = get_kw_or_pos("arc_size", None, None)

        if br is None or tr is None or h is None:
            return None, "Cannot create Cone (missing radii/height)"

        obj = doc.addObject("Part::Cone", obj_name)
        obj.Radius1 = float(br)
        obj.Radius2 = float(tr)
        obj.Height = float(h)
        if ang is not None:
            obj.Angle = float(ang)

        return obj, "Created Cone"

    return None, f"Unsupported primitive: {func}"


# ----------------------------
# Update existing FreeCAD objects from build123d calls
# ----------------------------
def _update_obj_from_call(obj, func_name, args, kwargs):
    """
    Mutate an existing Part::* object based on build123d primitive params.
    Returns True if changes made.
    """
    changed = False

    def set_prop(prop_name, new_val):
        nonlocal changed
        try:
            cur = getattr(obj, prop_name)
            # FreeCAD properties sometimes are floats or Quantity-like
            cur_val = float(cur) if isinstance(cur, (int, float)) else float(getattr(cur, "Value", cur))
            if abs(cur_val - float(new_val)) > 1e-6:
                setattr(obj, prop_name, float(new_val))
                changed = True
        except Exception:
            try:
                setattr(obj, prop_name, float(new_val))
                changed = True
            except Exception:
                pass

    def get_kw_or_pos(key, pos_idx, default=None):
        if key in kwargs and kwargs[key] is not None:
            return kwargs[key]
        if pos_idx is not None and pos_idx < len(args) and args[pos_idx] is not None:
            return args[pos_idx]
        return default

    # Box
    if obj.TypeId == "Part::Box" and func_name == "Box":
        l = get_kw_or_pos("length", 0, None)
        w = get_kw_or_pos("width", 1, None)
        h = get_kw_or_pos("height", 2, None)
        if l is not None:
            set_prop("Length", l)
        if w is not None:
            set_prop("Width", w)
        if h is not None:
            set_prop("Height", h)

    # Cylinder
    if obj.TypeId == "Part::Cylinder" and func_name == "Cylinder":
        r = get_kw_or_pos("radius", 0, None)
        h = get_kw_or_pos("height", 1, None)
        if r is not None:
            set_prop("Radius", r)
        if h is not None:
            set_prop("Height", h)

    # Sphere
    if obj.TypeId == "Part::Sphere" and func_name == "Sphere":
        r = get_kw_or_pos("radius", 0, None)
        if r is not None:
            set_prop("Radius", r)

        a1 = get_kw_or_pos("arc_size1", None, None)
        a2 = get_kw_or_pos("arc_size2", None, None)
        a3 = get_kw_or_pos("arc_size3", None, None)
        if a1 is not None:
            set_prop("Angle1", a1)
        if a2 is not None:
            set_prop("Angle2", a2)
        if a3 is not None:
            set_prop("Angle3", a3)

    # Cone
    if obj.TypeId == "Part::Cone" and func_name == "Cone":
        br = get_kw_or_pos("bottom_radius", 0, None)
        tr = get_kw_or_pos("top_radius", 1, None)
        h = get_kw_or_pos("height", 2, None)
        ang = get_kw_or_pos("arc_size", None, None)

        if br is not None:
            set_prop("Radius1", br)
        if tr is not None:
            set_prop("Radius2", tr)
        if h is not None:
            set_prop("Height", h)
        if ang is not None:
            set_prop("Angle", ang)

    return changed


# ----------------------------
# Main entry
# ----------------------------
def inject_code_to_freecad(full_code):
    doc = FreeCAD.ActiveDocument
    if not doc:
        return False, "No Document"

    try:
        compile(full_code, "<string>", "exec")
    except SyntaxError:
        return False, "Syntax Error"

    # Execute once to obtain local_env (variables, numeric expr resolution)
    local_env = {}
    try:
        exec("from build123d import *", local_env)
        exec(full_code, local_env)
    except Exception as e:
        return False, f"Runtime Error: {e}"

    # -----------------------------------------
    # CODE-FIRST: if no Part:: objects exist, create one from `part = ...`
    # -----------------------------------------
    created_any = False
    created_msg = None

    if not _doc_has_non_shadow_parts(doc):
        part_call = _extract_first_part_call(full_code, local_env)
        if part_call:
            func_name, args, kwargs = part_call

            # Prefer header name if user has "# Something"
            header_pat = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", re.MULTILINE)
            m = header_pat.search(full_code)
            base_name = m.group(1) if m else "CodeCAD_Part"
            obj_name = _make_unique_name(doc, base_name)

            obj, msg = _create_freecad_primitive_from_part_call(doc, obj_name, func_name, args, kwargs)
            if obj is None:
                return False, msg

            try:
                doc.recompute()
            except Exception:
                pass

            # Default to build123d origin
            _enable_b123d_origin(obj)

            # Apply any Pos(...) * part translations from code (optional but useful)
            delta = _extract_pos_translation(full_code, local_env)
            if delta is not None:
                try:
                    obj.Placement.Base = obj.Placement.Base.add(delta)
                except Exception:
                    pass

            try:
                doc.recompute()
            except Exception:
                pass

            created_any = True
            created_msg = msg

    # -----------------------------------------
    # NORMAL PATH: sync updates into existing objects using block headers
    # -----------------------------------------
    block_pattern = re.compile(r"^#\s*(\w+)", re.MULTILINE)

    lines = full_code.split("\n")
    current_obj_name = None
    changes_made = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        m_block = block_pattern.match(line)
        if m_block:
            current_obj_name = m_block.group(1)
            continue

        if not current_obj_name:
            continue

        obj = doc.getObject(current_obj_name)
        if not obj:
            # If code-first created object with a different name (due to collisions),
            # we won't try to guess; header-driven updates require name match.
            continue

        # Only react to lines that look like primitive creation
        if "Box(" in line or "Cylinder(" in line or "Sphere(" in line or "Cone(" in line:
            # Extract expression from first primitive token to end of line, parse as Call
            idx = None
            for token in ["Box(", "Cylinder(", "Sphere(", "Cone("]:
                j = line.find(token)
                if j != -1:
                    idx = j
                    break
            if idx is None:
                continue

            expr = line[idx:]
            try:
                call_tree = ast.parse(expr, mode="eval")
                if not isinstance(call_tree.body, ast.Call):
                    continue
                call = call_tree.body
                func_name = None
                if isinstance(call.func, ast.Name):
                    func_name = call.func.id
                elif isinstance(call.func, ast.Attribute):
                    func_name = call.func.attr
                if not func_name:
                    continue

                args = [_eval_ast_expr(a, local_env) for a in call.args]
                kwargs = {}
                for kw in call.keywords:
                    if kw.arg is None:
                        continue
                    kwargs[kw.arg] = _eval_ast_expr(kw.value, local_env)

                if _update_obj_from_call(obj, func_name, args, kwargs):
                    changes_made = True

            except Exception:
                continue

    if changes_made:
        try:
            doc.recompute()
        except Exception:
            pass
        return True, "Synced"

    if created_any:
        return True, created_msg or "Created"

    return True, "No Changes"