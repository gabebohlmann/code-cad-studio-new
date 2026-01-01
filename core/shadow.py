import FreeCAD
import FreeCAD.Part as PartModule
import tempfile
import os

def save_any_shape(obj, path):
    if hasattr(obj, "part"): obj = obj.part
    elif hasattr(obj, "sketch"): obj = obj.sketch
    if hasattr(obj, "export_brep"):
        try:
            obj.export_brep(path)
            return True
        except: pass
    if hasattr(obj, "wrapped"):
        try:
            from OCP.BRepTools import BRepTools
            BRepTools.Write_s(obj.wrapped, path)
            return True
        except: pass
    return False

class Build123dShadow:
    def __init__(self, obj):
        if not hasattr(obj, "Code"):
            obj.addProperty("App::PropertyString", "Code", "Build123d", "Generated Code")
        obj.Proxy = self

    def execute(self, obj):
        # Silent Syntax Check
        try: compile(obj.Code, '<string>', 'exec')
        except SyntaxError: return 

        try:
            local_env = {}
            exec("from build123d import *", local_env)
            exec(obj.Code, local_env)
            if 'part' in local_env:
                raw_obj = local_env['part']
                fd, temp_path = tempfile.mkstemp(suffix=".brep")
                os.close(fd)
                try:
                    success = save_any_shape(raw_obj, temp_path)
                    if success:
                        new_shape = PartModule.Shape()
                        new_shape.read(temp_path)
                        new_shape.translate(FreeCAD.Base.Vector(60, 0, 0)) 
                        obj.Shape = new_shape
                finally:
                    if os.path.exists(temp_path): os.remove(temp_path)
        except Exception:
            pass

    def onChanged(self, obj, prop):
        if prop == "Code": obj.touch()

class Build123dViewProvider:
    def __init__(self, vobj): vobj.Proxy = self
    def getIcon(self): return ":/icons/Part_Feature.svg"
    def attach(self, vobj): self.ViewObject = vobj
    def updateData(self, fp, prop): pass

def ensure_shadow_object():
    doc = FreeCAD.ActiveDocument 
    if not doc: return None
    obj = doc.getObject("Build123d_Shadow")
    if not obj:
        obj = doc.addObject("Part::FeaturePython", "Build123d_Shadow")
        Build123dShadow(obj)
        Build123dViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.0, 1.0, 0.0)
        obj.ViewObject.Transparency = 60
    return obj