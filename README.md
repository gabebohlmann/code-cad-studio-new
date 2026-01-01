# code-cad-studio
A FreeCAD workbench for bidirectional sync between FreeCAD and a Build123d code panel

## TODO
1. Figure out why Build123d based exporting isn't working and only BREP Tools will work
1. Look into why FreeCAD (OCCT?) can't solve corner fillet geometry when you do a face and then columns of a cube. (columns and then face works because both are cylindrical fillets presumambly, whereas a face fillet does "spherical" fillets in corners)
1. Decide what to do with sliders when a var is an order of magnitude larger (currently they all reset too the middle point and have individual scales)
1. Update sliders to reset scale when max value is lowered
1. Add table functionality to slider tab
