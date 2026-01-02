# core/shadow.py

import FreeCAD
import FreeCAD.Part as PartModule
import tempfile
import os


def _gui_up() -> bool:
    """True when FreeCAD is running with GUI (FreeCADGui loaded)."""
    try:
        return bool(getattr(FreeCAD, "GuiUp", False))
    except Exception:
        return False


def _get_location_obj(bobj):
    """
    Try to extract a build123d Location-like object from common attribute names.
    build123d has historically used .location and also introduced .global_location.
    """
    loc = None
    if hasattr(bobj, "global_location"):
        try:
            loc = bobj.global_location
        except Exception:
            loc = None
    if loc is None and hasattr(bobj, "location"):
        try:
            loc = bobj.location
        except Exception:
            loc = None
    return loc


def _bake_location_into_wrapped(bobj):
    """
    Return a TopoDS_Shape with location baked into geometry so BREP export preserves transforms.

    Why: build123d exporters often write `obj.wrapped` which may not include `obj.location`
    transforms in a baked way. This makes translation/rotation via Pos/Rot appear to do nothing
    in your shadow.
    """
    if not hasattr(bobj, "wrapped"):
        return None

    shape = bobj.wrapped
    loc = _get_location_obj(bobj)
    if loc is None:
        return shape

    # build123d Location usually wraps an OCCT TopLoc_Location in `loc.wrapped`
    toploc = None
    if hasattr(loc, "wrapped"):
        try:
            toploc = loc.wrapped
        except Exception:
            toploc = None

    if toploc is None:
        return shape

    try:
        # TopLoc_Location -> gp_Trsf
        trsf = toploc.Transformation()

        # Bake into geometry (not just a Location tag)
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

        # copy=True to avoid mutating source
        xform = BRepBuilderAPI_Transform(shape, trsf, True)
        baked = xform.Shape()
        return baked
    except Exception:
        # If anything goes wrong, fall back to raw wrapped
        return shape


def save_any_shape(obj, path):
    """
    Save build123d objects to BREP, preserving transforms (Pos/Rot) by baking location.

    Supports:
      - obj.part / obj.sketch wrapping
      - obj.wrapped (TopoDS_Shape)
      - obj.export_brep as fallback, but we prefer our own writer so we don't lose location
    """
    # Unwrap common build123d containers
    if hasattr(obj, "part"):
        obj = obj.part
    elif hasattr(obj, "sketch"):
        obj = obj.sketch

    # Preferred: bake location into wrapped and write with BRepTools
    baked = _bake_location_into_wrapped(obj)
    if baked is not None:
        try:
            from OCP.BRepTools import BRepTools
            BRepTools.Write_s(baked, path)
            return True
        except Exception:
            pass

    # Fallback: try build123d's own export_brep
    if hasattr(obj, "export_brep"):
        try:
            obj.export_brep(path)
            return True
        except Exception:
            pass

    # Last resort: write raw wrapped (may lose location)
    if hasattr(obj, "wrapped"):
        try:
            from OCP.BRepTools import BRepTools
            BRepTools.Write_s(obj.wrapped, path)
            return True
        except Exception:
            pass

    return False


class Build123dShadow:
    def __init__(self, obj):
        if not hasattr(obj, "Code"):
            obj.addProperty("App::PropertyString", "Code", "Build123d", "Generated Code")

        # Optional display offset (keeps old side-by-side behavior)
        if not hasattr(obj, "DisplayOffset"):
            obj.addProperty(
                "App::PropertyVector",
                "DisplayOffset",
                "Build123d",
                "World-space display offset applied to the shadow shape (for side-by-side viewing).",
            )
            obj.DisplayOffset = FreeCAD.Base.Vector(60, 0, 0)

        obj.Proxy = self

    def execute(self, obj):
        # Silent Syntax Check
        try:
            compile(obj.Code, "<string>", "exec")
        except SyntaxError:
            return

        try:
            local_env = {}
            exec("from build123d import *", local_env)
            exec(obj.Code, local_env)

            if "part" not in local_env:
                return

            raw_obj = local_env["part"]

            fd, temp_path = tempfile.mkstemp(suffix=".brep")
            os.close(fd)

            try:
                success = save_any_shape(raw_obj, temp_path)
                if success:
                    new_shape = PartModule.Shape()
                    new_shape.read(temp_path)

                    # Display offset (defaults to +X 60mm); safe even in headless
                    try:
                        off = getattr(obj, "DisplayOffset", FreeCAD.Base.Vector(60, 0, 0))
                        if off and (abs(off.x) > 1e-12 or abs(off.y) > 1e-12 or abs(off.z) > 1e-12):
                            new_shape.translate(off)
                    except Exception:
                        pass

                    obj.Shape = new_shape
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception:
            # Keep previous “silent fail” behavior.
            pass

    def onChanged(self, obj, prop):
        if prop == "Code":
            obj.touch()


class Build123dViewProvider:
    """
    GUI-only view provider. Must not be required in headless (FreeCADCmd).
    """
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return ":/icons/Part_Feature.svg"

    def attach(self, vobj):
        self.ViewObject = vobj

    def updateData(self, fp, prop):
        pass


def ensure_shadow_object():
    """
    Headless-safe:
      - Creates the App object always
      - Only touches ViewObject / ViewProvider when GUI is up and ViewObject exists
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        return None

    obj = doc.getObject("Build123d_Shadow")

    if not obj:
        obj = doc.addObject("Part::FeaturePython", "Build123d_Shadow")
        Build123dShadow(obj)

        # GUI-only view setup
        if _gui_up() and hasattr(obj, "ViewObject") and obj.ViewObject:
            try:
                Build123dViewProvider(obj.ViewObject)
            except Exception:
                pass
            try:
                obj.ViewObject.ShapeColor = (0.0, 1.0, 0.0)
                obj.ViewObject.Transparency = 60
            except Exception:
                pass

    else:
        # If it exists but is missing Proxy/properties (e.g. after reload), repair it.
        try:
            if not hasattr(obj, "Proxy") or obj.Proxy is None or not isinstance(obj.Proxy, Build123dShadow):
                Build123dShadow(obj)
        except Exception:
            try:
                Build123dShadow(obj)
            except Exception:
                pass

        if _gui_up() and hasattr(obj, "ViewObject") and obj.ViewObject:
            # Ensure a view provider exists (safe no-op if already assigned)
            try:
                if getattr(obj.ViewObject, "Proxy", None) is None:
                    Build123dViewProvider(obj.ViewObject)
            except Exception:
                pass
            try:
                obj.ViewObject.ShapeColor = (0.0, 1.0, 0.0)
                obj.ViewObject.Transparency = 60
            except Exception:
                pass

    return obj