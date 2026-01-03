# InitGui.py

import FreeCAD
import FreeCADGui


class ToggleStudioPanelCommand:
    """Command to toggle the Code-CAD Studio Panel"""

    def GetResources(self):
        return {
            "Pixmap": "Std_ViewScreenShot",
            "MenuText": "Toggle Studio Panel",
            "ToolTip": "Show/Hide the Code-CAD Studio Panel",
        }

    def Activated(self):
        try:
            import gui.dock
            gui.dock.toggle_panel()
        except Exception as e:
            FreeCAD.Console.PrintError(f"Error executing command: {e}\n")

    def IsActive(self):
        return True


FreeCADGui.addCommand("ToggleStudioPanel", ToggleStudioPanelCommand())


class CodeCADStudioWorkbench(FreeCADGui.Workbench):
    def __init__(self):
        self.__class__.Icon = "Std_ViewScreenShot"
        self.__class__.MenuText = "Code-CAD Studio"
        self.__class__.ToolTip = "Bi-directional Code & GUI Modeling"

    def Initialize(self):
        self.appendToolbar("Studio Tools", ["ToggleStudioPanel"])
        self.appendMenu("Code-CAD", ["ToggleStudioPanel"])

        # Optional auto-launch (keep if you like; safe because InitGui runs only with GUI)
        try:
            import gui.dock
            gui.dock.create_panel()
        except Exception as e:
            FreeCAD.Console.PrintError(f"Auto-launch error: {e}\n")

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CodeCADStudioWorkbench())