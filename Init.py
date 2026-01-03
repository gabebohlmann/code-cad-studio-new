# Init.py

# Keep minimal. Optionally register CLI helpers, nothing GUI-related.

# If you want, expose core engine helpers:
from core.engine import SyncEngine
from core.freecad_api import FreeCADAPI

def make_engine():
    return SyncEngine(FreeCADAPI())
