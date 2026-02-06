# gui/commands.py

import FreeCAD
import FreeCADGui
import gui.dock

class ToggleStudioPanelCommand:
    """
    Standard FreeCAD Gui Command to toggle the Code-CAD Studio dock panel.
    
    This class is registered with the FreeCAD Command Manager (usually in `InitGui.py`).
    It handles the toolbar button's appearance and behavior.
    """
    
    def GetResources(self):
        """
        Defines the icon, text, and tooltip for the command.
        
        Returns:
            dict: A dictionary containing:
                - 'Pixmap' (str): Icon name (registered resource or built-in).
                - 'MenuText' (str): Text displayed in the menu.
                - 'ToolTip' (str): Text displayed on hover.
        """
        # You can replace 'Std_ViewScreenShot' with a path to your icon.svg if you have one
        return {
            'Pixmap': 'Std_ViewScreenShot', 
            'MenuText': 'Toggle Studio Panel',
            'ToolTip': 'Show/Hide the Code-CAD Studio Panel'
        }

    def Activated(self):
        """
        Executed when the user clicks the toolbar button or menu item.
        
        Delegates the actual visibility logic to the `gui.dock` module.
        """
        # Calls the function in dock.py
        gui.dock.toggle_panel()

    def IsActive(self):
        """
        Determines whether the command is enabled.
        
        Returns:
            bool: True if the command can be executed (always active in this WB).
        """
        return True