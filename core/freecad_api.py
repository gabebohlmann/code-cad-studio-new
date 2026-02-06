# core/freecad_api.py

import sys
import traceback
import FreeCAD


class FreeCADAPI:
    """
    Tiny adapter layer for FreeCAD operations.

    This class provides a unified interface for basic document handling and 
    geometry creation that is safe to use in both the standard GUI and the 
    headless `FreeCADCmd` environment. It explicitly avoids importing 
    `FreeCADGui` or `PySide` to prevent crashes in console-only modes.
    """

    def _log_error(self, msg: str):
        """
        Headless-safe error logging.

        Attempts to use the FreeCAD Console for visible red text in the GUI. 
        Falls back to standard error (stderr) if running headlessly or if the 
        console is unavailable.

        Args:
            msg (str): The error message to log.
        """ 
        try:
            FreeCAD.Console.PrintError(msg + "\n")
        except Exception:
            print(msg, file=sys.stderr, flush=True)

    def active_doc(self):
        """
        Retrieves the currently active FreeCAD document.

        Returns:
            App.Document | None: The active document object, or None if no document is open.
        """
        return FreeCAD.ActiveDocument

    def recompute(self, doc=None):
        """
        Trigger a recompute of the specified document.

        Catches and logs any exceptions that occur during the recompute process 
        to prevent crashing the main thread.

        Args:
            doc (App.Document, optional): The document to recompute. 
                Defaults to the active document.
        """
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
        """
        Creates a FreeCAD Base Vector.

        Args:
            x (float, optional): X coordinate. Defaults to 0.0.
            y (float, optional): Y coordinate. Defaults to 0.0.
            z (float, optional): Z coordinate. Defaults to 0.0.

        Returns:
            FreeCAD.Base.Vector: The resulting 3D vector object.
        """
        return FreeCAD.Base.Vector(float(x), float(y), float(z))

    def is_gui_up(self):
        """
        Checks if FreeCAD is currently running in GUI mode.

        Returns:
            bool: True if the GUI is active, False if running in console/headless mode.
        """
        # FreeCAD sets this flag when GUI is running
        return bool(getattr(FreeCAD, "GuiUp", False))

    def ensure_doc(self, name="Doc"):
        """
        Ensures a document exists, creating a new one if necessary.

        Args:
            name (str, optional): The name to use for the new document if 
                creation is required. Defaults to "Doc".

        Returns:
            App.Document: The active or newly created document.
        """
        if FreeCAD.ActiveDocument:
            return FreeCAD.ActiveDocument
        return FreeCAD.newDocument(name)