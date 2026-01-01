# core/parser.py

import FreeCAD
import re

def resolve_value(val_str, local_env):
    try: return float(val_str)
    except:
        if val_str in local_env:
            try: return float(local_env[val_str])
            except: pass
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
    if not doc: return False, "No Document"

    try: compile(full_code, '<string>', 'exec')
    except SyntaxError: return False, "Syntax Error"

    local_env = {}
    try:
        exec("from build123d import *", local_env)
        exec(full_code, local_env)
    except Exception as e: return False, f"Runtime Error: {e}"

    block_pattern = re.compile(r"^#\s*(\w+)", re.MULTILINE)
    box_pattern = re.compile(r"Box\s*\(\s*([a-zA-Z0-9_\.]+)\s*,\s*([a-zA-Z0-9_\.]+)\s*,\s*([a-zA-Z0-9_\.]+)")
    param_pattern = re.compile(r"(radius|length)\s*=\s*([a-zA-Z0-9_\.]+)")

    lines = full_code.split('\n')
    current_obj_name = None
    changes_made = False

    for line in lines:
        line = line.strip()
        if not line: continue
        m_block = block_pattern.match(line)
        if m_block:
            current_obj_name = m_block.group(1); continue
        if not current_obj_name: continue
        obj = doc.getObject(current_obj_name)
        if not obj: continue

        if obj.TypeId == "Part::Box":
            m_box = box_pattern.search(line)
            if m_box:
                l = resolve_value(m_box.group(1), local_env)
                w = resolve_value(m_box.group(2), local_env)
                h = resolve_value(m_box.group(3), local_env)
                if l is not None and abs(obj.Length.Value - l) > 1e-4: obj.Length.Value = l; changes_made = True
                if w is not None and abs(obj.Width.Value - w) > 1e-4: obj.Width.Value = w; changes_made = True
                if h is not None and abs(obj.Height.Value - h) > 1e-4: obj.Height.Value = h; changes_made = True
        elif obj.TypeId in ["Part::Fillet", "Part::Chamfer"]:
            m_param = param_pattern.search(line)
            if m_param:
                val = resolve_value(m_param.group(2), local_env)
                if val is not None:
                    if obj.TypeId == "Part::Fillet" and hasattr(obj, "Radius") and abs(obj.Radius.Value - val) > 1e-4:
                         obj.Radius.Value = val; changes_made = True
                    elif obj.TypeId == "Part::Chamfer" and hasattr(obj, "Size") and abs(obj.Size.Value - val) > 1e-4:
                        obj.Size.Value = val; changes_made = True
    if changes_made:
        doc.recompute()
        return True, "Synced"
    return True, "No Changes"