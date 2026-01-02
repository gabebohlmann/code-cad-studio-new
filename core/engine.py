# core/engine.py

# core/engine.py

import FreeCAD

from core.transpiler import transpile_object
from core.parser import inject_code_to_freecad
from core.shadow import ensure_shadow_object
from core.verifier import compare_shapes


class SyncEngine:
    """
    Headless-safe orchestration layer:
    - Finds "tip" object
    - GUI->Code (transpile)
    - Code->GUI (inject)
    - Shadow update
    - Verification
    - Origin toggle (FreeCAD origin <-> build123d origin)
    """

    def __init__(self, api):
        self.api = api

    # -------------------------------------------------------------------------
    # Tip discovery (same logic you had in Dock)
    # -------------------------------------------------------------------------
    def find_tip_object(self, doc=None):
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

    # -------------------------------------------------------------------------
    # GUI -> Code
    # -------------------------------------------------------------------------
    def code_from_tip(self, tip_obj):
        if not tip_obj:
            return ""
        return "from build123d import *\n\n" + transpile_object(tip_obj)

    # -------------------------------------------------------------------------
    # Code -> GUI (apply to FreeCAD params) + Shadow update
    # -------------------------------------------------------------------------
    def apply_code_to_freecad(self, code: str):
        """
        Apply code to FreeCAD primitives/params (your parser.inject_code_to_freecad).
        Returns (success, message).
        """
        return inject_code_to_freecad(code)

    def update_shadow_code(self, code: str):
        """
        Update the shadow object's Code property.
        NOTE: ensure_shadow_object must be headless-safe; if not, patch it (see note below).
        """
        shadow = ensure_shadow_object()
        if shadow:
            try:
                shadow.Code = code
                shadow.touch()
            except Exception:
                pass
        return shadow

    # -------------------------------------------------------------------------
    # Verification
    # -------------------------------------------------------------------------
    def verify(self, tip_obj, shadow_obj):
        return compare_shapes(tip_obj, shadow_obj)

    # -------------------------------------------------------------------------
    # Origin toggle (moved from Dock; GUI calls this)
    # -------------------------------------------------------------------------
    def _ensure_origin_props(self, obj):
        """Add per-object props if missing."""
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
        Compute bbox center in *local* coordinates (object space), even if Placement has rotation.
        """
        shp = getattr(obj, "Shape", None)
        if not shp:
            return None
        try:
            bb = shp.BoundBox
            if not bb:
                return None
            c_world = bb.Center
        except Exception:
            return None

        try:
            inv = obj.Placement.inverse()
            c_local = inv.multVec(c_world)
            return c_local
        except Exception:
            try:
                base = obj.Placement.Base
                return FreeCAD.Base.Vector(c_world.x - base.x, c_world.y - base.y, c_world.z - base.z)
            except Exception:
                return None

    def _find_root_object_for_origin(self, tip):
        """
        For origin changes, prefer applying to the *base primitive* if tip is a modifier.
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
        Return (root_obj, using_b123d_origin_bool) for current tip, or (None, False).
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
        Toggle between:
          - FreeCAD origin (default): CodeCAD_UseB123dOrigin = False
          - build123d origin: CodeCAD_UseB123dOrigin = True and Placement shifted by bbox-center
        Returns (ok: bool, message: str, using_b123d_origin: bool)
        """
        if not tip_obj:
            return False, "No Part", False

        root = self._find_root_object_for_origin(tip_obj)
        if not root:
            return False, "No Part", False

        self._ensure_origin_props(root)

        using = bool(root.CodeCAD_UseB123dOrigin)

        # ---- If currently using build123d origin -> restore FreeCAD origin (inverse)
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

        # ---- Otherwise enable build123d origin
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