# cli_test.py

import FreeCAD as App
import Part

doc = App.newDocument("CliTest")

box = doc.addObject("Part::Box", "Box")
box.Length = 10
box.Width  = 20
box.Height = 30

doc.recompute()

# Save the FreeCAD file
doc.saveAs("CliTest.FCStd")

# Export as BREP (very reliable headless export)
Part.export([box.Shape], "box.brep")

print("Wrote CliTest.FCStd and box.brep")