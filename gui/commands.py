# gui/commands.py

import FreeCAD
import FreeCADGui
import gui.dock

class ToggleStudioPanelCommand:
    """Command to toggle the visibility of the Code-CAD Studio dock panel."""
    
    def GetResources(self):
        # You can replace 'Std_ViewScreenShot' with a path to your icon.svg if you have one
        return {
            'Pixmap': 'Std_ViewScreenShot', 
            'MenuText': 'Toggle Studio Panel',
            'ToolTip': 'Show/Hide the Code-CAD Studio Panel'
        }

    def Activated(self):
        # Calls the function in dock.py
        gui.dock.toggle_panel()

    def IsActive(self):
        # Always active when the workbench is loaded
        return True