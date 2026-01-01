import FreeCAD
import FreeCADGui
import sys
import os

# 1. SETUP PATH GLOBALLY
# We add this immediately so the subsequent class definitions can find the modules
PATH_TO_MOD = r"C:\Users\gabeb\AppData\Roaming\FreeCAD\Mod\CodeCADStudio"
if PATH_TO_MOD not in sys.path:
    sys.path.append(PATH_TO_MOD)

# 2. DEFINE COMMAND
class ToggleStudioPanelCommand:
    """Command to toggle the Code-CAD Studio Panel"""
    
    def GetResources(self):
        return {
            'Pixmap': 'Std_ViewScreenShot', 
            'MenuText': 'Toggle Studio Panel',
            'ToolTip': 'Show/Hide the Code-CAD Studio Panel'
        }

    def Activated(self):
        try:
            # We can import safely because we updated sys.path above
            import gui.dock
            gui.dock.toggle_panel()
        except Exception as e:
            FreeCAD.Console.PrintError(f"Error executing command: {e}\n")

    def IsActive(self):
        return True

# 3. REGISTER COMMAND GLOBALLY
# This happens immediately when the file is read, avoiding scope issues later.
FreeCADGui.addCommand('ToggleStudioPanel', ToggleStudioPanelCommand())

# 4. DEFINE WORKBENCH
class CodeCADStudioWorkbench(FreeCADGui.Workbench):
    def __init__(self):
        self.__class__.Icon = "Std_ViewScreenShot"
        self.__class__.MenuText = "Code-CAD Studio"
        self.__class__.ToolTip = "Bi-directional Code & GUI Modeling"

    def Initialize(self):
        # Setup UI using the command string name (registered above)
        self.appendToolbar("Studio Tools", ["ToggleStudioPanel"])
        self.appendMenu("Code-CAD", ["ToggleStudioPanel"])
        
        # Auto-launch Panel
        try:
            import gui.dock
            gui.dock.create_panel()
        except Exception as e:
            FreeCAD.Console.PrintError(f"Auto-launch error: {e}\n")

    def GetClassName(self):
        # MUST be this specific string for Python workbenches
        return "Gui::PythonWorkbench"

# 5. REGISTER WORKBENCH
FreeCADGui.addWorkbench(CodeCADStudioWorkbench())