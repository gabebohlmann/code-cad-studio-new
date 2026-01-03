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

[1]: https://wiki.freecad.org/Scripted_objects?utm_source=chatgpt.com "Scripted objects"
[2]: https://forum.freecad.org/viewtopic.php?style=2&t=77953&utm_source=chatgpt.com "(1) Collaboration - best practice?"