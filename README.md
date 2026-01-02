# code-cad-studio
A FreeCAD workbench for bidirectional sync between FreeCAD and a Build123d code panel

## TODO
  1. Figure out why Build123d based exporting isn't working and only BREP Tools will work
  1. Look into why FreeCAD (OCCT?) can't solve corner fillet geometry when you do a face and then columns of a cube. (columns and then face works because both are cylindrical fillets presumambly, whereas a face fillet does "spherical" fillets in corners)
  1. Decide what to do with sliders when a var is an order of magnitude larger (currently they all reset too the middle point and have individual scales)
  1. Update sliders to reset scale when max value is lowered
  1. Add table functionality to slider tab
  1. Make shadow.py a fully headless cli compatible mesh generator
  1. Small note about naming Header-driven sync (# Box → object named Box) still relies on name matching. In code-first, if you paste code and there’s already a collision in the document, it will create Box1, Box2, etc. That’s usually fine, but if you want name-stable sync later, the next evolution is: store a persistent ID on the object and include it in the code header (e.g., # Box [id=...]). Not needed yet.
  1. Account for when b123d and FC origin are the same (sphere)
  1. Add b123d variables to varset sync
  1. Fix variable slider scale breaking when only one variable
  1. Fix FC object losing b123d origin when making cone starting from b123d code panel and then increasing h from slider

## Build123d algebra mode vs. FreeCAD Part Workbench feature parity
  * b123d object class works with algebra and builder mode so some objects that are based on sketch geometry (Part Design WB) in FC don't work with in FC Part WB such as Hole, CounterSinkHole, CounterBoleHole. Wedge is a bulit in object in b123d that would need to built by an extruded custom polygon in FC I believe
  * 
