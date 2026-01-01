import FreeCAD
import re

def resolve_value(val_str, local_env):
    try:
        return float(val_str)
    except:
        if val_str in local_env:
            try:
                return float(local_env[val_str])
            except:
                pass
    return None

def parse_variables(code):
    """Extracts variable names and values from code string."""
    vars_found = []
    lines = code.split('\n')
    pattern = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([-+]?[0-9]*\.?[0-9]+)$")
    for idx, line in enumerate(lines):
        match = pattern.match(line.strip())
        if match:
            vars_found.append({'name': match.group(1), 'value': float(match.group(2))})
    return vars_found

def inject_code_to_freecad(full_code):
    doc = FreeCAD.ActiveDocument
    if not doc:
        return False, "No Document"

    try:
        compile(full_code, '<string>', 'exec')
    except SyntaxError:
        return False, "Syntax Error"

    local_env = {}
    try:
        exec("from build123d import *", local_env)
        exec(full_code, local_env)
    except Exception as e:
        return False, f"Runtime Error: {e}"

    # block headers: "# ObjectName"
    block_pattern = re.compile(r"^#\s*(\w+)", re.MULTILINE)

    # Primitive patterns
    box_pattern = re.compile(
        r"Box\s*\(\s*([a-zA-Z0-9_\.]+)\s*,\s*([a-zA-Z0-9_\.]+)\s*,\s*([a-zA-Z0-9_\.]+)"
    )

    # Cylinder (keyword style preferred by your transpiler)
    cyl_radius_kw = re.compile(r"\bradius\s*=\s*([a-zA-Z0-9_\.]+)")
    cyl_height_kw = re.compile(r"\bheight\s*=\s*([a-zA-Z0-9_\.]+)")

    # Sphere keywords (build123d names)
    sph_radius_kw = re.compile(r"\bradius\s*=\s*([a-zA-Z0-9_\.]+)")
    sph_a1_kw = re.compile(r"\barc_size1\s*=\s*([a-zA-Z0-9_\.]+)")
    sph_a2_kw = re.compile(r"\barc_size2\s*=\s*([a-zA-Z0-9_\.]+)")
    sph_a3_kw = re.compile(r"\barc_size3\s*=\s*([a-zA-Z0-9_\.]+)")

    # Modifier params (existing)
    param_pattern = re.compile(r"(radius|length)\s*=\s*([a-zA-Z0-9_\.]+)")

    lines = full_code.split('\n')
    current_obj_name = None
    changes_made = False

    for line in lines:
        raw = line
        line = line.strip()
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
            continue

        # -------------------------
        # Part::Box
        # -------------------------
        if obj.TypeId == "Part::Box":
            m_box = box_pattern.search(line)
            if m_box:
                l = resolve_value(m_box.group(1), local_env)
                w = resolve_value(m_box.group(2), local_env)
                h = resolve_value(m_box.group(3), local_env)

                if l is not None and abs(obj.Length.Value - l) > 1e-4:
                    obj.Length.Value = l
                    changes_made = True
                if w is not None and abs(obj.Width.Value - w) > 1e-4:
                    obj.Width.Value = w
                    changes_made = True
                if h is not None and abs(obj.Height.Value - h) > 1e-4:
                    obj.Height.Value = h
                    changes_made = True

        # -------------------------
        # Part::Cylinder (NEW: allow code->GUI updates)
        # -------------------------
        elif obj.TypeId == "Part::Cylinder":
            if "Cylinder" in line:
                mr = cyl_radius_kw.search(line)
                mh = cyl_height_kw.search(line)

                r = resolve_value(mr.group(1), local_env) if mr else None
                h = resolve_value(mh.group(1), local_env) if mh else None

                if r is not None and hasattr(obj, "Radius") and abs(obj.Radius.Value - r) > 1e-4:
                    obj.Radius.Value = r
                    changes_made = True
                if h is not None and hasattr(obj, "Height") and abs(obj.Height.Value - h) > 1e-4:
                    obj.Height.Value = h
                    changes_made = True

        # -------------------------
        # Part::Sphere (NEW)
        # -------------------------
        elif obj.TypeId == "Part::Sphere":
            if "Sphere" in line:
                mr = sph_radius_kw.search(line)
                m1 = sph_a1_kw.search(line)
                m2 = sph_a2_kw.search(line)
                m3 = sph_a3_kw.search(line)

                r = resolve_value(mr.group(1), local_env) if mr else None
                a1 = resolve_value(m1.group(1), local_env) if m1 else None
                a2 = resolve_value(m2.group(1), local_env) if m2 else None
                a3 = resolve_value(m3.group(1), local_env) if m3 else None

                if r is not None and hasattr(obj, "Radius") and abs(obj.Radius.Value - r) > 1e-4:
                    obj.Radius.Value = r
                    changes_made = True

                # Only update angles if they appear in code
                if a1 is not None and hasattr(obj, "Angle1") and abs(obj.Angle1.Value - a1) > 1e-4:
                    obj.Angle1.Value = a1
                    changes_made = True
                if a2 is not None and hasattr(obj, "Angle2") and abs(obj.Angle2.Value - a2) > 1e-4:
                    obj.Angle2.Value = a2
                    changes_made = True
                if a3 is not None and hasattr(obj, "Angle3") and abs(obj.Angle3.Value - a3) > 1e-4:
                    obj.Angle3.Value = a3
                    changes_made = True

        # -------------------------
        # Fillet / Chamfer
        # -------------------------
        elif obj.TypeId in ["Part::Fillet", "Part::Chamfer"]:
            m_param = param_pattern.search(line)
            if m_param:
                val = resolve_value(m_param.group(2), local_env)
                if val is not None:
                    if obj.TypeId == "Part::Fillet" and hasattr(obj, "Radius") and abs(obj.Radius.Value - val) > 1e-4:
                        obj.Radius.Value = val
                        changes_made = True
                    elif obj.TypeId == "Part::Chamfer" and hasattr(obj, "Size") and abs(obj.Size.Value - val) > 1e-4:
                        obj.Size.Value = val
                        changes_made = True

    if changes_made:
        doc.recompute()
        return True, "Synced"

    return True, "No Changes"