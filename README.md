# code-cad-studio
A FreeCAD workbench for bidirectional sync between FreeCAD and a Build123d code panel

## How to run server
  1. cd server
  1. .\.venv\Scripts\Activate.ps1
  1. python -m uvicorn server.app:app --reload --host 127.0.0.1 --port 8000

## TODO
  1. Fix web ui 
  1. Add strict type checking
  1. Check docstring correctness with ruff and pydoc lint
  1. Make server/app.py actually grab a real env var for FREECAD_CMD
  1. Shouldn't these build123d helpers be isolated out from the dock.py?
      _round3()
      selector_for_vertex()
      selector_for_edge()
      ... 
  1. Add strict typing (there was a settings somewhere in vs code for linting or something to enforce stricter typing)
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
  1. Add a better dialog to indicate sync direction GUI to code shows but not code to GUI
  1. Change parser back to AST and do the architecture improvements described by chatGPT in parser.py in commit #691011a96f682b50c07a24abcf031ca04d008c2f
  1. Investigate translation necessity in shadow.py
                    try:
                        off = getattr(obj, "DisplayOffset", FreeCAD.Base.Vector(60, 0, 0))
  1. Add a shadow offset button
  1. Mitigate code execution safety issues discussed in the api/macro chatgpt chat below
  1. in core/freecad_api.py  Add save_as(path) helper (so engine/CLI scripts don’t reach into FreeCAD directly).
  1. Make selectors work in CLI. Here is a chatgpt note on it " What to do with selection + tuner features?

    Selection (FreeCADGui.Selection) and tuner sliders (Qt widgets) are GUI-only by nature.

    If you want parity in headless, the equivalent is:

    headless: accept “selector requests” via API arguments (e.g., “pick the top face”) or by stable naming

    GUI: generate those selector expressions automatically from the current selection (your existing code)

    So: keep selection generation in gui/, and keep selector execution (pure build123d text inserted into code) in core/."
  1. Possibly remove all FreeCAD.(...) or at least FreeCAD.Part as it is apparently error causing from within FreeCAD python env (use just Part or other)
  1. Figure out why initial recompute loads for along time and can crash entire program but subsequent part deletes and readds (assume it recomputes?) are snappy
  1. Switch to 2 spaces tabs
  1. in core/engine.py
      figure out if this is the right heuristic or if tip heuristics even matter. make a diagram of how and why tip matters
        leaves = [c for c in candidates if c not in parents]
        return leaves[-1] if leaves else None
  1. Consider removing from Build123d import * in the frontend code
  1. Standardize function comments and documentation
  1. possible duplication of import should probably check if full_code includes import in parser.py 
    exec("from build123d import *", local_env)
    exec(full_code, local_env)
  1. Make exec() in parser.py safer by making a .py file wrapper to validate build123d or other arbitrary code execution mitigation
  1. Check that "baking" location in shadow.py makes the most sense. Doesn't matter as shadow but does it persist into export?
  1. This code in shadow.py may need the not removed
     \# Optional display offset (keeps old side-by-side behavior)
     if not hasattr(obj, "DisplayOffset"):
  1. Figure out why ensure_shadow() and get_shadow_object() should both exist, they seem redundand or remove ensure_shadow() obj return
  1. Why is this the origin in FC? in core/verifier.py
    \# Clone and align shadow back to origin for comparison
    s2_aligned = s2.copy()
    s2_aligned.translate(FreeCAD.Base.Vector(-60, 0, 0))
  1. What is the "CodeCAD" argument doingin engine.py?
   obj.addProperty(
                "App::PropertyBool",
                "CodeCAD_UseB123dOrigin",
                "CodeCAD",
                "If true, prefer build123d default origin/alignment for generated code.",
            )"
  1. Investigate this ChatGPT function comment in core/engine.py
      def _shape_bbox_center_local(self, obj):
        """
        IMPORTANT:
        In FreeCAD, obj.Shape is typically in *local* coordinates; Placement is applied separately.
        Therefore Shape.BoundBox.Center is already local for Part:: primitives.
        """
  1. Probably better to pass/return origin state as a string "b123d" or "fc" instead of a boolean of either one and hope user/coder remembers which one
  in core/engine.py
    return root, bool(root.CodeCAD_UseB123dOrigin)
  1. Investigate this ChatGPT comment
    def toggle_origin_for_tip(self, tip_obj):
        """
        Toggles alignment between FreeCAD default (Center of Mass) and build123d default (Origin).
      * is the position in the viewer in the .fcstd or .step exports or is centering the viewer origin on the COM purely visual? a ChatGPT comment elsewhere implied that pos() was set outside of the core object class so that may affect how things are exported right? how do other CAD packages manage positional information in their file types and exports? would a .sldprt and a .step export from solidworks from the same file import into another program at the same position? 
  1. Investigate this ChatGPT comment further.     
      def _shape_bbox_center_local(self, obj):
        """
        Calculates the center of the object's bounding box in local coordinates.

        In FreeCAD, `obj.Shape` is typically defined in local space relative to
        `obj.Placement`. Therefore, `Shape.BoundBox.Center` gives us the 
        geometric center relative to the object's origin (0,0,0).
  1. Add more in code comments, will save this for a full reread for a release candidate when I understand the FC and b123d APIs better
  1. Standardize function parameter names shape vs shp vs geo_shape etc.
  1. Investigate _safe_center() in transpiler.py. how do points and vertexes return a center? is it for when the geo_shape is jsut that object?
  1. Investigate face selectors in transpiler.py
    if st == "Face":
            try:
                n = geo_shape.normalAt(0, 0)
                if abs(n.z) > 0.99:
                    return f"part.faces().sort_by(Axis.Z).{'last' if c.z > 0 else 'first'}"
  1. What are edgelinks? core/transpiler.py
    if hasattr(obj, "EdgeLinks") and isinstance(obj.EdgeLinks, tuple) and len(obj.EdgeLinks) > 1:
  1. In transpiler.py this is kind of jank. Makes more sense when you look at what has to be done for sphere i guess tho.
      def _is_default(v, d):
              try:
                  return abs(float(v) - float(d)) < 1e-9
              except Exception:
                  return False

          is_full = _is_default(ang, 360.0)
  1. Investigate in transpiler.py
           if not _use_b123d_origin(obj):
            c_local = _bbox_center_local(obj)
            if c_local is not None:
                cx, cy, cz = float(c_local.x), float(c_local.y), float(c_local.z)
                if abs(cx) > 1e-9 or abs(cy) > 1e-9 or abs(cz) > 1e-9:
                    lines.append(f"part = Pos({cx:.6f}, {cy:.6f}, {cz:.6f}) * part")
  1. Investigate fillets in parser.py
    elif obj.TypeId in ["Part::Fillet", "Part::Chamfer"]:
        parent = None
        if hasattr(obj, "Base"):
            parent = obj.Base
  1. Consider pulling FreeCAD imports out of every file except freecad_api.py
  here is a ChatGPT chat on that. Read API ChatGPT chat header below
  1. Code duplicated in api and shadow.py
    def _gui_up() -> bool:
    """True when FreeCAD is running with GUI (FreeCADGui loaded)."""
    try:
        return bool(getattr(FreeCAD, "GuiUp", False))
    except Exception:
        return False
  1. Why are OCP imports in core/shadow.py in the code itself and not at the top? are they resource intensive so only called when neccesary
  1. Possibly redundant from Build123d import * in shadow.py
  1. Does uv mean something? in gui/dock.py
      uv = face_shape.Surface.parameter(c)
      n = face_shape.normalAt(uv[0], uv[1])
  1. This > or < 1 method seems buggy in gui/dock.selector_for_face
  1. what is super in ParameterWidget.__init__()? just a QT widget?
  1. Figure out the mechanics of ParameterWidget.update_state() and (...).on_slide()
  1. What does gui_to_code_suppressed(), self.panel.programmatic_update do in gui/dock.py?
  1. slotChangedObject(), slotCreatedObject(), and slotDeletedObject() are strange in gui/dock.py there all basically wrappers for self.panel.trigger_gui_to_code_update(),  B123dSelectionObserver() class methods are similar as wrappers for self.panel.update_selector_from_current_selection()
  1. in gui/dock.py this super call doesn't make sense to me 
      class B123dDockWidget(QtGui.QDockWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
  1. How does this work in gui/dock.py
      class B123dDockWidget(QtGui.QDockWidget):
        def __init__(self, parent=None):
        ...
            # IMPORTANT: prevents GUI->Code overwrite right after code application
            self._suppress_gui_to_code_until = 0.0
      
      and 

            self.observer = B123dLiveSyncObserver(self)
            FreeCAD.addDocumentObserver(self.observer)
  1. what do pl and pc mean in B123dDockWidget.__init__()
  l2.addWidget(QtGui.QLabel("Variables (Common Scale):"))
            self.pl = QtGui.QVBoxLayout()
            self.pl.setAlignment(QtCore.Qt.AlignTop)
            pc = QtGui.QWidget()
            pc.setLayout(self.pl)
            l2.addWidget(pc)
  1. Who delete later in dock.py?
                # Clear tuner widgets
                for name in list(self.param_widgets.keys()):
                    try:
                        self.param_widgets[name].deleteLater()
  1. Add a reset_panel function to dock.py that clear_panel_no_part() will use so that the code is more seperated concerns
  1. Test the 300 ms pause
          def trigger_gui_to_code_update(self):
            if self.gui_to_code_suppressed():
                return
            self.status.setText("Reading FreeCAD…")
            self.status.setStyleSheet("background: #ddf; color: blue; padding: 5px;")
            self.timer_gui_to_code.start(300)
  1. Track how code var is generated in dock.py
    code = self.engine.code_from_tip(tip)
  1. .deleteLater() in dock.py how does it work
  1. In dock.py why  *2 ?
      this_limit = scale_limit if scale_limit else (val * 2.0 if val != 0 else 1.0)
  1. How does dock.py update_slider() apply to current code? seems like it appends on update
  1. How to find undocumented functions or variables in code programatticaly 
  1. Possibly fix the strange way dock.py nests the entire class inside an if/else
  1. Add mouseover (preselect) functionality in the 3d view for highlighting code blocks/lines in the code cad window dock.py.B123dSelectionObservers.setPreselection()
  1. Handle objects that have same FC and B123d origin better by greying out the orign switch button and telling user they are the same
  1. ChatGPT TODOs after repo scan 5/22/26
  What I would do next
          I’d resume development in this order:
          Make the current repo boringly runnable. Add missing imports/type fixes, run ruff, run py_compile, and make one smoke test for box_example.py → FreeCAD object → shadow → verify.
          Define the true source of truth. For Git-native CAD, I would not make arbitrary Python the canonical storage format. I would define a small JSON/YAML IR with stable IDs, then generate build123d Python as a view/export format. Python can remain the power-user mode.
          Replace name-based sync with persistent IDs. Something like:

      # Box [id=6f4a...]
      part = Box(L, W, H)

      or better, store ID in the IR and store the same ID in a FreeCAD custom property.

      Move selector logic out of gui/dock.py. The GUI should detect what the user selected; the core should know how to express that as build123d selectors. Your README already points in this direction.
      Treat cloud execution as hostile. The server path is promising, but exec() plus arbitrary build123d code means the cloud version needs sandboxing, containers, timeouts, file/network restrictions, and probably AST whitelisting or IR-first execution.
  1. 

  

## Build123d algebra mode vs. FreeCAD Part Workbench feature parity
  * b123d object class works with algebra and builder mode so some objects that are based on sketch geometry (Part Design WB) in FC don't work with in FC Part WB such as Hole, CounterSinkHole, CounterBoleHole. Wedge is a bulit in object in b123d that would need to built by an extruded custom polygon in FC I believe

## Important ChatGPT chat on using macro/api code to save code cad like data directly from FreeCAD
  * ### Is there an “FCStd → .py” conversion tool in FreeCAD?

Not really in the sense you’re imagining.

FreeCAD’s native document format (`.FCStd`) is *data*, not a canonical “source code” representation. A big reason is security: FreeCAD explicitly avoids embedding executable code inside FreeCAD files (“for security reasons… files never carry any embedded code”). ([FreeCAD Wiki][1])

So the little `.py` I gave you wasn’t “generated from an FCStd spec”; it was just *normal FreeCAD API usage* (`doc.addObject(...)`, set properties, `doc.recompute()`, then save/export).

You *can* build an “export to Python script” yourself for many cases by walking the document tree and emitting:

* `doc.addObject(obj.TypeId, obj.Name)`
* then `obj.<PropertyName> = ...` for selected properties
* then `obj.Placement = ...`
* then `doc.recompute()`

…but for arbitrary parts/feature trees this quickly becomes workbench-specific, order-dependent, and sometimes not reversible (expressions, links, “Base” references, sketches, etc.). There isn’t a universal one-size “FCStd → Python” that FreeCAD treats as authoritative.

(Also: `.FCStd` is basically a zip container with XML + embedded shapes/resources, which is why it’s convenient for headless automation and exporting.) ([FreeCAD Forum][2])

---

### Is FreeCAD secretly doing “code-cad” internally?

No. The “intermediary” is the **document object model** (objects + properties + links) and recompute logic that produces OCCT shapes.

* The GUI creates/edits objects and properties.
* On recompute, each object generates a `Shape` using OCCT.
* Python is just **one API surface** to do the same operations the GUI does.

So your instinct is good: *macro/API-level Python is a very real “ground truth” interface to FreeCAD* — but it’s still an API for manipulating the model graph, not a hidden canonical “source language.”

---

### How do I find the API calls for any GUI command?

In practice there are 3 reliable routes:

1. **Macro recording / “Python logging”**
   Record a macro while you click the GUI command(s). FreeCAD will emit Python that reproduces (most of) what you just did.
   Caveat: not every GUI action logs perfectly, and some workbenches do more complex things than a clean API call.

2. **Inspect the created object**
   After using the GUI tool, select the object and inspect in the Python console:

   * `obj.TypeId`
   * `obj.PropertiesList`
   * `obj.getGroupOfProperty("Length")` (helps classify properties)
   * `obj.Placement`, `obj.Shape.BoundBox`, etc.

3. **Command name → `runCommand`** (GUI only)
   In GUI context you can often reproduce a command by name, e.g. `FreeCADGui.runCommand("Part_Box")`, then inspect what it created.

---

## About your plan: “promote macro/API code as first-class” — will FreeCAD devs hate it?

If you do it responsibly, probably not.

FreeCAD already embraces scripting/macro workflows, but they’re cautious about **auto-executing untrusted code**. That’s the line.

Where you’ll get pushback (especially for a core PR) is anything that:

* stores executable code *inside* `.FCStd` and auto-runs it on open/recompute, or
* encourages opening models that silently execute arbitrary Python.

That’s exactly the trojan/code-injection concern you noticed, and it’s why FreeCAD documents aim not to carry embedded code. ([FreeCAD Wiki][1])

As an **external workbench**, you have way more latitude, as long as you:

* **don’t auto-execute** code from a file without an explicit user action + warning,
* and provide a safe/default path.

---

## Managing the real risk in *your* current architecture

Right now, the biggest hazard is **not** “storing code in FCStd” — it’s that your pipeline executes user text via `exec(...)` (parser + shadow), which means a “part script” can do *anything* on the user’s machine (filesystem, network, etc.) unless you constrain it.

A “code checker” can absolutely help, but it needs to be more than regex.

### What I’d recommend as the safety model

**1) Define a declarative intermediate format (IR) as your “safe” file**

* Example: JSON like:

  ```json
  {"op":"Box","args":{"x":10,"y":20,"z":30},"placement":[0,0,0],"originMode":"b123d"}
  ```
* This is *data*, not code. Easy to validate and diff.

**2) Treat Python/build123d scripts as “unsafe mode”**

* Only run them with an explicit “Run Script (Unsafe)” action.
* Show a warning like a macro warning: “This will execute Python.”

**3) If you want “script-like but safe,” do AST whitelisting**

* Parse with `ast.parse`
* Reject anything except:

  * numeric literals / simple arithmetic
  * assignments to variables
  * a whitelist of calls: `Box`, `Cylinder`, `Sphere`, `Cone`, `Torus`, `Pos`, `Rot`, maybe boolean ops later
* Reject `import`, attribute access, subscripting, `open()`, `__*__`, etc.

**4) Cloud/headless: always run in isolation**
Even with AST checks, for cloud you’ll still want a container/VM sandbox. The good news: your current split (core logic vs GUI) is already *very* compatible with that direction.

---

## How this maps to FreeCADCmd in the future

Your current layout is already close to a CLI-friendly design:

* `core/*` modules: good candidates to be the engine
* `gui/dock.py`: should become a thin UI wrapper only

To reduce GUI reliance *now*, the key architectural move is:

### ✅ Create a “headless engine” entrypoint (no Qt, no FreeCADGui)

Something like `core/engine.py` with functions:

* `load_or_new_doc(path=None)`
* `apply_b123d_code_to_doc(code)  -> (created/updated objects)`
* `transpile_doc_to_b123d(tip_obj) -> code`
* `export(doc, brep/step/stl)`
* `verify(fc_shape, shadow_shape)`

Then:

* GUI calls `engine.*`
* CLI script calls `engine.*`
* Cloud worker calls `engine.*`

This lets you run the same behavior in **FreeCADCmd locally** without containers, and later wrap it in containers for cloud.

---

## Should you embed code inside FCStd?

If you do, I’d keep it to **non-executed text properties** (like you already do with `Build123d_Shadow.Code`) and/or your declarative IR.

Best practice for safety + community alignment:

* Store **IR** inside FCStd (or as a sidecar file).
* Store **Python** only as optional export/import, never auto-run.
* Provide a clear “trust boundary” UI.

That keeps you aligned with FreeCAD’s security posture while still making “code-cad” a first-class workflow.

If you want, paste your current `inject_code_to_freecad()` and I’ll outline exactly how to add a **Safe Mode** path (AST whitelist, no `exec`) without breaking your current functionality.

## API ChatGPT Chat
    You are spot on. It is a bit arbitrary, but there is a subtle architectural distinction at play here: Data Types vs. Business Logic.

The method vector() is in freecad_api.py because it is a Factory for a Primitive Data Type. It doesn't "do" anything to your project; it just gives you a value object.

In contrast, the "geometry methods" in engine.py (like find_tip_object) are Application Logic. They define how your specific workbench functions.

Here is the breakdown of why this separation exists (and where it is arguably imperfect):
1) The vector() method is a "Safe Factory"

If you look closely at the implementation in freecad_api.py:
Python

def vector(self, x=0.0, y=0.0, z=0.0):
    return FreeCAD.Base.Vector(float(x), float(y), float(z))

It performs Input Sanitization.

    Native FreeCAD: FreeCAD.Base.Vector("10", "10", "10") will crash (TypeError) because the C++ bindings expect numbers, not strings.

    Your API: api.vector("10", "10", "10") works perfectly because it casts to float first.

Since your parser.py deals heavily with extracting strings from text files, having this "Safe Factory" in your lowest-level API prevents crashes from bad data types. It belongs in freecad_api.py because it is a generic utility, not specific to the logic of "Code-CAD".
2) engine.py contains "Domain Logic"

Methods like find_tip_object or toggle_origin_for_tip are not generic FreeCAD operations. They represent opinions specific to your application:

    "The tip is the last object that isn't a Shadow." (Opinion)

    "We should move the placement to match the bounding box center." (Opinion)

If you put these in freecad_api.py, you would pollute your clean "Adapter Layer" with complex business rules.
3) The Arbitrary Part (Critique)

You are right that it is inconsistent because files like core/engine.py and core/parser.py import FreeCAD directly anyway.

    Strict Architecture: If you were being 100% strict, engine.py would never import FreeCAD. It would call self.api.create_box(...) or self.api.get_objects().

    Pragmatic Architecture: You (or the AI) likely decided that wrapping every single FreeCAD function (like doc.addObject, obj.Shape.Edges, obj.Placement) was too much work.

Conclusion: freecad_api.py became a home for "Unsafe or Generic things" (logging, recomputing, type casting), while engine.py became the home for "The actual application." The vector() method sits in the API because it is a generic utility helper, essentially extending the FreeCAD capabilities to be safer for Python strings.

[1]: https://wiki.freecad.org/Scripted_objects?utm_source=chatgpt.com "Scripted objects"
[2]: https://forum.freecad.org/viewtopic.php?style=2&t=77953&utm_source=chatgpt.com "(1) Collaboration - best practice?"