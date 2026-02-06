# InitGui.py

"""
Workbench Initialization (GUI Mode).

This file is the entry point for the FreeCAD GUI. It is automatically executed 
by FreeCAD when the workbench is selected from the dropdown menu.

Responsibilities:
1. Define and register GUI commands (buttons).
2. Define the Workbench class (toolbars, menus).
3. Initialize the main dock panel on load.
"""

import FreeCAD
import FreeCADGui


class ToggleStudioPanelCommand:
    """
    Standard FreeCAD Gui Command to toggle the Code-CAD Studio dock panel.
    """

    def GetResources(self):
        """
        Defines the icon, text, and tooltip for the command.

        Returns:
            dict: UI resources map (Pixmap, MenuText, ToolTip).
        """
        return {
            "Pixmap": "Std_ViewScreenShot",
            "MenuText": "Toggle Studio Panel",
            "ToolTip": "Show/Hide the Code-CAD Studio Panel",
        }

    def Activated(self):
        """
        Executed when the user clicks the toolbar button or menu item.

        Lazily imports the GUI module to ensure dependencies are loaded 
        only when needed.
        """
        try:
            import gui.dock
            gui.dock.toggle_panel()
        except Exception as e:
            FreeCAD.Console.PrintError(f"Error executing command: {e}\n")

    def IsActive(self):
        """
        Determines whether the command is enabled.

        Returns:
            bool: Always True for this workbench.
        """
        return True

# Register the command with FreeCAD's internal command manager
FreeCADGui.addCommand("ToggleStudioPanel", ToggleStudioPanelCommand())


class CodeCADStudioWorkbench(FreeCADGui.Workbench):
    """
    The main Workbench definition class.

    This class configures how the workbench appears in the FreeCAD interface,
    defining its icon, menus, and toolbars.
    """
    def __init__(self):
        """
        Initializes workbench metadata (Icon, MenuText, ToolTip).
        """
        self.__class__.Icon = "Std_ViewScreenShot"
        self.__class__.MenuText = "Code-CAD Studio"
        self.__class__.ToolTip = "Bi-directional Code & GUI Modeling"

    def Initialize(self):
        """
        Called when the workbench is activated by the user.

        1. Creates the "Studio Tools" toolbar.
        2. Creates the "Code-CAD" menu.
        3. Auto-launches the main dock panel.
        """
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