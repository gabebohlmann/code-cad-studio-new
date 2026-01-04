# core/freecad_api.py

import sys
import traceback
import FreeCAD


class FreeCADAPI:
    """
    Tiny adapter layer.
    - Safe to use in headless FreeCADCmd.
    - No FreeCADGui / PySide.
    """

    def _log_error(self, msg: str):
        """
        Headless-safe error logging.
        Prefer FreeCAD.Console.PrintError; fall back to stderr print.
        """
        try:
            FreeCAD.Console.PrintError(msg + "\n")
        except Exception:
            print(msg, file=sys.stderr, flush=True)

    def active_doc(self):
        return FreeCAD.ActiveDocument

    def recompute(self, doc=None):
        doc = doc or self.active_doc()
        if not doc:
            return
        try:
            doc.recompute()
        except Exception as e:
            # Log both a short message and a traceback for debugging.
            self._log_error(f"[FreeCADAPI] doc.recompute() failed: {e!r}")
            self._log_error(traceback.format_exc())

    def vector(self, x=0.0, y=0.0, z=0.0):
        return FreeCAD.Base.Vector(float(x), float(y), float(z))

    def is_gui_up(self):
        # FreeCAD sets this flag when GUI is running
        return bool(getattr(FreeCAD, "GuiUp", False))

    def ensure_doc(self, name="Doc"):
        if FreeCAD.ActiveDocument:
            return FreeCAD.ActiveDocument
        return FreeCAD.newDocument(name)