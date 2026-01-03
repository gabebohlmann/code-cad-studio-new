# core/freecad_api.py

import FreeCAD


class FreeCADAPI:
    """
    Tiny adapter layer.
    - Safe to use in headless FreeCADCmd.
    - No FreeCADGui / PySide.
    """

    def active_doc(self):
        return FreeCAD.ActiveDocument

    def recompute(self, doc=None):
        doc = doc or self.active_doc()
        if doc:
            try:
                doc.recompute()
            except Exception:
                pass

    def vector(self, x=0.0, y=0.0, z=0.0):
        return FreeCAD.Base.Vector(float(x), float(y), float(z))

    def is_gui_up(self):
        # FreeCAD sets this flag when GUI is running
        return bool(getattr(FreeCAD, "GuiUp", False))
    
    def ensure_doc(self, name="Doc"):
        if FreeCAD.ActiveDocument:
            return FreeCAD.ActiveDocument
        return FreeCAD.newDocument(name)

