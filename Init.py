# Init.py

"""
Workbench Initialization (Headless/Console Mode).

This file is executed when FreeCAD loads the workbench in console mode 
(e.g., via `FreeCADCmd`). It is also executed in GUI mode, but `InitGui.py` 
handles the UI components.

CRITICAL:
    Do NOT import `FreeCADGui`, `PySide`, or any `gui.*` modules here.
    Doing so will cause the workbench to crash when running on a headless server.
"""

# could expose core engine helpers here
from core.engine import SyncEngine
from core.freecad_api import FreeCADAPI

def make_engine():
    """
    Factory helper to create a SyncEngine instance with the default API adapter.
    
    Useful for scripts running in the FreeCAD console that want to access 
    Code-CAD features without setting up the full GUI.

    Returns:
        SyncEngine: An initialized engine instance ready for headless use.
    """
    return SyncEngine(FreeCADAPI())
