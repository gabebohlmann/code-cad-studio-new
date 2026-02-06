# core/engine.py

import FreeCAD

from core.transpiler import transpile_object
from core.parser import inject_code_to_freecad, parse_variables
from core.shadow import ensure_shadow_object
from core.verifier import compare_shapes


class SyncEngine:
    """
    The headless-safe orchestration layer that acts as the central controller for 
    the Code-CAD Studio workbench.
    
    Acts as a facade for the Parser, Transpiler, and Shadow modules, managing 
    the bi-directional synchronization between the FreeCAD document state 
    and the build123d Python code.
        - Finds "tip" object
        - GUI -> Code (transpile)
        - Code -> GUI (inject)
        - Shadow update
        - Verification
        - Origin toggle (FreeCAD origin <-> build123d origin)

    Attributes:
        api (FreeCADAPI): Adapter for FreeCAD operations.
    """

    def __init__(self, api):
        self.api = api

    def parse_variables(self, code: str):
        """
        Extracts variable definitions from the provided code for the UI Tuner.

        Args:
            code (str): The raw Python code string.

        Returns:
            list[dict]: A list of dicts, e.g., [{'name': 'L', 'value': 10.0}, ...].
        """
        try:
            return parse_variables(code)
        except Exception:
            return []

    def find_tip_object(self, doc=None):
        """
        Locates the 'Tip' (terminal) object in the document dependency graph.

        The 'Tip' is essentially the final result of the modeling operations.
        It heuristicly filters for 'Part::' objects that are not parents of 
        any other object.

        Args:
            doc (App.Document, optional): The document to search. Defaults to active doc.

        Returns:
            object | None: The FreeCAD DocumentObject representing the tip, or None.
        """
        doc = doc or self.api.active_doc()
        if not doc:
            return None

        candidates = set()
        for obj in doc.Objects:
            if obj.Name != "Build123d_Shadow" and obj.TypeId.startswith("Part::"):
                candidates.add(obj)

        if not candidates:
            return None

        parents = set()
        for obj in candidates:
            if hasattr(obj, "Base"):
                if isinstance(obj.Base, (list, tuple)):
                    for i in obj.Base:
                        if hasattr(i, "Name"):
                            parents.add(i)
                else:
                    parents.add(obj.Base)

            if hasattr(obj, "EdgeLinks") and isinstance(obj.EdgeLinks, tuple) and len(obj.EdgeLinks) > 0:
                if hasattr(obj.EdgeLinks[0], "Name"):
                    parents.add(obj.EdgeLinks[0])

        leaves = [c for c in candidates if c not in parents]
        return leaves[-1] if leaves else None

    def code_from_tip(self, tip_obj):
        """
        Generates build123d Python code representing the given FreeCAD object.

        Args:
            tip_obj (object): The FreeCAD object to transpile.

        Returns:
            str: The generated Python code including imports.
        """
        if not tip_obj:
            return ""
        return "from build123d import *\n\n" + transpile_object(tip_obj)

    def apply_code_to_freecad(self, code: str):
        """
        Parses the provided code and injects parameter values into existing FreeCAD objects.

        This performs the Code -> GUI synchronization direction.

        Args:
            code (str): The Python source code.

        Returns:
            tuple[bool, str]: (Success boolean, Status message).
        """
        return inject_code_to_freecad(code)

    def ensure_shadow(self):
        """
        Ensures the 'Build123d_Shadow' object exists in the document.

        Returns:
            object: The shadow object.
        """
        return ensure_shadow_object()

    def get_shadow_object(self, doc=None):
        """
        Retrieves the shadow object if it exists.

        Args:
            doc (App.Document, optional): The document to check.

        Returns:
            object | None: The shadow object or None.
        """
        doc = doc or self.api.active_doc()
        if not doc:
            return None
        try:
            return doc.getObject("Build123d_Shadow")
        except Exception:
            return None

    def update_shadow_code(self, code: str):
        """
        Updates the 'Code' property of the shadow object.
        
        This triggers the shadow's internal `execute()` method on recompute.

        Args:
            code (str): The new Python code.

        Returns:
            object | None: The updated shadow object.
        """
        shadow = ensure_shadow_object()
        if shadow:
            try:
                shadow.Code = code
                shadow.touch()
            except Exception:
                pass
        return shadow

    def remove_shadow(self, doc=None):
        """
        Removes the shadow object from the document.

        Args:
            doc (App.Document, optional): The document to modify.

        Returns:
            bool: True if removed or not present, False if error.
        """
        doc = doc or self.api.active_doc()
        if not doc:
            return False

        shadow = self.get_shadow_object(doc)
        if not shadow:
            return True

        try:
            doc.removeObject(shadow.Name)
            return True
        except Exception:
            return False

    def verify(self, tip_obj, shadow_obj):
        """
        Compares the FreeCAD object (tip) against the Shadow object.

        Args:
            tip_obj (object): The native FreeCAD object.
            shadow_obj (object): The Code-generated shadow object.

        Returns:
            tuple[bool, str]: (True if match, Reason string).
        """
        return compare_shapes(tip_obj, shadow_obj)

    def _ensure_origin_props(self, obj):
        """
        Adds the necessary CodeCAD properties to an object if they are missing.

        Injects 'CodeCAD_UseB123dOrigin' (Bool) and 'CodeCAD_OriginDelta' (Vector)
        into the FreeCAD object to track its alignment state.

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

    def _shape_bbox_center_local(self, obj):
        """
        Calculates the center of the object's bounding box in local coordinates.

        In FreeCAD, `obj.Shape` is typically defined in local space relative to
        `obj.Placement`. Therefore, `Shape.BoundBox.Center` gives us the 
        geometric center relative to the object's origin (0,0,0).

        Args:
            obj (App.DocumentObject): The object to inspect.

        Returns:
            FreeCAD.Base.Vector | None: The center vector, or None if the shape is invalid.
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

    def _find_root_object_for_origin(self, tip):
        """
        Walks up the dependency chain to find the 'Base' primitive.

        When applying origin toggles, we cannot move a modifier (like a Fillet)
        directly; we must move the underlying primitive (like the Box) that 
        defines the coordinate space.

        Args:
            tip (App.DocumentObject): The currently selected tip object.

        Returns:
            App.DocumentObject | None: The ancestor primitive (e.g., Box) or the tip itself.
        """
        obj = tip
        seen = set()

        while obj and hasattr(obj, "Name") and obj.Name not in seen:
            seen.add(obj.Name)

            if obj.TypeId in ["Part::Fillet", "Part::Chamfer"]:
                base = getattr(obj, "Base", None)
                if isinstance(base, tuple):
                    base = base[0]
                if base:
                    obj = base
                    continue

            return obj

        return tip

    def get_origin_state(self, tip_obj):
        """
        Determines the current origin mode of the tip object's root.

        Args:
            tip_obj (object): The object to inspect.

        Returns:
            tuple[object | None, bool]: (The root object, True if using build123d origin).
        """
        if not tip_obj:
            return None, False
        root = self._find_root_object_for_origin(tip_obj)
        if not root:
            return None, False
        self._ensure_origin_props(root)
        try:
            return root, bool(root.CodeCAD_UseB123dOrigin)
        except Exception:
            return root, False

    def toggle_origin_for_tip(self, tip_obj):
        """
        Toggles alignment between FreeCAD default (Center of Mass) and build123d default (Origin).

        Moves the object's Placement to visually maintain position while changing 
        the internal origin logic.

        Args:
            tip_obj (object): The object to toggle.

        Returns:
            tuple[bool, str, bool]: (Success, Message, New State is Build123d?).
        """
        if not tip_obj:
            return False, "No Part", False

        root = self._find_root_object_for_origin(tip_obj)
        if not root:
            return False, "No Part", False

        self._ensure_origin_props(root)

        using = bool(root.CodeCAD_UseB123dOrigin)

        # If currently using build123d origin -> restore FreeCAD origin
        if using:
            delta_world = getattr(root, "CodeCAD_OriginDelta", FreeCAD.Base.Vector(0, 0, 0))
            try:
                root.Placement.Base = root.Placement.Base.add(delta_world)
                root.CodeCAD_UseB123dOrigin = False
                root.CodeCAD_OriginDelta = FreeCAD.Base.Vector(0, 0, 0)
                self.api.recompute()
                return True, "Restored (FreeCAD origin)", False
            except Exception:
                return False, "Failed to restore origin", True

        # Otherwise enable build123d origin
        c_local = self._shape_bbox_center_local(root)
        if c_local is None:
            return False, "Origin toggle failed (no bbox)", False

        # Convert local delta into world using rotation
        try:
            rot = root.Placement.Rotation
            delta_world = rot.multVec(c_local)
        except Exception:
            delta_world = c_local

        try:
            root.Placement.Base = root.Placement.Base.sub(delta_world)
            root.CodeCAD_OriginDelta = delta_world
            root.CodeCAD_UseB123dOrigin = True
            self.api.recompute()
            return True, "Switched (build123d origin)", True
        except Exception:
            return False, "Failed to switch origin", False

    def apply_pipeline(self, code: str, *, make_shadow: bool = True, verify: bool = True):
        """
        Executes the full Code -> GUI synchronization pipeline.

        Sequence:
        1. Inject code params into FreeCAD objects.
        2. Update Shadow object code.
        3. Recompute document.
        4. Verify geometry match.

        Args:
            code (str): The Python code to process.
            make_shadow (bool, optional): Whether to update the shadow. Defaults to True.
            verify (bool, optional): Whether to run geometric verification. Defaults to True.

        Returns:
            dict: Result dictionary containing keys: 'ok', 'message', 'tip', 'shadow', 'verified', 'verify_reason'.
        """
        ok, msg = self.apply_code_to_freecad(code)

        if not ok:
            return {
                "ok": False,
                "message": msg,
                "tip": None,
                "shadow": None,
                "verified": False,
                "verify_reason": "Not verified",
            }

        shadow = None
        if make_shadow:
            shadow = self.update_shadow_code(code)

        self.api.recompute()

        tip = self.find_tip_object()
        if not tip or not shadow or not verify:
            return {
                "ok": True,
                "message": msg,
                "tip": tip,
                "shadow": shadow,
                "verified": False,
                "verify_reason": "Skipped/Unavailable",
            }

        v_ok, v_reason = self.verify(tip, shadow)
        return {
            "ok": True,
            "message": msg,
            "tip": tip,
            "shadow": shadow,
            "verified": bool(v_ok),
            "verify_reason": v_reason,
        }