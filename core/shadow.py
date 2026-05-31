# core/shadow.py

import FreeCAD
import Part as PartModule
import tempfile
import os


def _gui_up() -> bool:
    """
    Checks if FreeCAD is currently running with the GUI subsystem loaded.

    Returns:
        bool: True if `FreeCAD.GuiUp` is set, False if running in headless/console mode.
    """
    try:
        return bool(getattr(FreeCAD, "GuiUp", False))
    except Exception:
        return False


def _get_location_obj(bobj):
    """
    Extracts the location object from a build123d entity.

    Build123d has historically changed how it exposes location (using `.location`
    vs `.global_location`). This helper tries standard attributes to find it.

    Args:
        bobj (object): The build123d object (Solid, Sketch, etc.).

    Returns:
        object | None: The underlying Location object if found, else None.
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
    Bakes the location of a build123d object into its underlying TopoDS_Shape.

    Crucial for export, as some formats ignore top-level location wrappers.

    Args:
        bobj (build123d.Topology): The build123d object.

    Returns:
        TopoDS_Shape: The OCCT shape with transforms applied to vertices.
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

def _is_build123d_result_candidate(value) -> bool:
    """
    Returns True if a value looks like a build123d object that can be displayed.

    This intentionally avoids depending on specific build123d classes so the
    shadow remains tolerant of build123d version differences.
    """
    if value is None:
        return False

    # Skip imported classes/functions from `from build123d import *`.
    if isinstance(value, type):
        return False

    if callable(value):
        return False

    # save_any_shape can handle objects with export_brep, wrapped, part, or sketch.
    return (
        hasattr(value, "export_brep")
        or hasattr(value, "wrapped")
        or hasattr(value, "part")
        or hasattr(value, "sketch")
    )


def _find_build123d_result(local_env):
    """
    Finds the build123d object that should be displayed by the shadow.

    Preferred behavior:
      1. Use a variable named `part` if it exists, preserving old behavior.
      2. Otherwise use the last user-created build123d-looking object.

    This supports normal build123d examples such as:
        ex2 = Box(length, width, thickness)
        ex2 -= Cylinder(center_hole_dia / 2, height=thickness)
    """
    preferred = local_env.get("part")
    if _is_build123d_result_candidate(preferred):
        return preferred

    for name, value in reversed(list(local_env.items())):
        if name.startswith("__"):
            continue

        if _is_build123d_result_candidate(value):
            return value

    return None

def save_any_shape(obj, path):
    """
    Exports a build123d object to a BREP file, preserving position/rotation.

    Standard build123d exporters often export the underlying geometry (`.wrapped`)
    without applying the object's local transformation (`.location`). This function
    "bakes" that location into the vertex coordinates before saving, ensuring
    the Shadow appears in the correct place in 3D space.

    Strategies (in order):
    1. Unwrap containers (`.part`, `.sketch`).
    2. Bake location and write via OCP `BRepTools`.
    3. Fallback to object's native `.export_brep()`.
    4. Fallback to writing raw `.wrapped` geometry.

    Args:
        obj (object): The build123d object to export.
        path (str): The destination file path.

    Returns:
        bool: True if export succeeded, False otherwise.
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
    """
    The Proxy class for the 'Build123d_Shadow' FreeCAD object.
    
    Executes Python code and visualizes the result.

    Attributes:
        obj (App.FeaturePython): The associated FreeCAD object.
    """

    def __init__(self, obj):
        """
        Initializes the shadow proxy and adds required properties.

        Args:
            obj (App.FeaturePython): The FreeCAD object instance.
        """
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
        """
        Executed during document recompute.

        Compiles and runs the code in `obj.Code`, then updates `obj.Shape`
        with the result.

        Args:
            obj (App.FeaturePython): The FreeCAD object instance.
        """
        try:
            compile(obj.Code, "<string>", "exec")
        except SyntaxError:
            return

        try:
            local_env = {}
            exec("from build123d import *", local_env)
            exec(obj.Code, local_env)

            raw_obj = _find_build123d_result(local_env)
            if raw_obj is None:
                return

            fd, temp_path = tempfile.mkstemp(suffix=".brep")
            os.close(fd)

            try:
                success = save_any_shape(raw_obj, temp_path)
                if success:
                    new_shape = PartModule.Shape()
                    new_shape.read(temp_path)

                    # Display offset (defaults to +X 60mm); safe even in headless
                    # TODO: investigate translation necessity
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
    The ViewProvider for the shadow object (GUI only).

    Manages the visual appearance (green transparency).
    """

    def __init__(self, vobj):
        """
        Initializes the ViewProvider proxy.

        Args:
            vobj (App.ViewObject): The FreeCAD ViewObject to attach to.
        """
        vobj.Proxy = self

    def getIcon(self):
        """Returns the path to the icon resource."""
        return ":/icons/Part_Feature.svg"

    def attach(self, vobj):
        """Attaches the provider to the ViewObject."""
        self.ViewObject = vobj

    def updateData(self, fp, prop):
        """
        Handles property updates for the view provider.

        Required by the FreeCAD ViewProvider interface, even if empty.

        Args:
            fp (App.FeaturePython): The feature object.
            prop (str): The name of the property that changed.
        """
        pass


def ensure_shadow_object():
    """
    Creates or retrieves the shadow object in the active document.
    
    Safe for headless execution (checks for GUI before accessing ViewObject).

    Returns:
        object | None: The shadow object.
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