# core/verifier.py

import FreeCAD

def compare_shapes(fc_obj, shadow_obj):
    if not fc_obj or not shadow_obj: return False, "Missing Objects"
    if not hasattr(fc_obj, "Shape") or not hasattr(shadow_obj, "Shape"): return False, "No Shape Data"

    s1 = fc_obj.Shape
    s2 = shadow_obj.Shape
    
    # Clone and align shadow back to origin for comparison
    s2_aligned = s2.copy()
    s2_aligned.translate(FreeCAD.Base.Vector(-60, 0, 0))

    # 1. TOPOLOGY CHECK
    if len(s1.Vertexes) != len(s2_aligned.Vertexes): 
        return False, f"Vertex Count: {len(s1.Vertexes)} vs {len(s2_aligned.Vertexes)}"
    if len(s1.Edges) != len(s2_aligned.Edges): 
        return False, f"Edge Count: {len(s1.Edges)} vs {len(s2_aligned.Edges)}"
    
    # 2. GEOMETRY CHECK (Safe Access)
    try:
        if abs(s1.Volume - s2_aligned.Volume) > 1e-6: 
            return False, f"Volume: {s1.Volume:.2f} vs {s2_aligned.Volume:.2f}"
    except: pass 

    try:
        c1 = s1.CenterOfMass
        c2 = s2_aligned.CenterOfMass
        dist = c1.distanceToPoint(c2)
        if dist > 1e-4: return False, f"CoM Offset: {dist:.5f}mm"
    except: pass

    return True, "Exact Match"