# gui/dock.py

import re
import time
import FreeCAD

# GUI IMPORTS (GUARDED so this module can be imported in FreeCADCmd safely)
try:
    import FreeCADGui
    from PySide import QtGui, QtCore
except Exception:
    FreeCADGui = None
    QtGui = None
    QtCore = None

# Headless-safe engine layer
from core.engine import SyncEngine
from core.freecad_api import FreeCADAPI
from core.snippets import SNIPPETS


def _gui_available() -> bool:
    """
    Checks if the full FreeCAD GUI environment (PySide + FreeCADGui) is loaded.

    Returns:
        bool: True if GUI modules are present and the GUI subsystem is up.
    """
    return (
        QtGui is not None
        and QtCore is not None
        and FreeCADGui is not None
        and bool(getattr(FreeCAD, "GuiUp", False))
    )


# If GUI isn't available, provide safe stubs so FreeCADCmd doesn't crash on import
if not _gui_available():

    def create_panel():
        raise RuntimeError("CodeCADStudio GUI is not available (FreeCADGui/PySide not loaded).")

    def toggle_panel():
        raise RuntimeError("CodeCADStudio GUI is not available (FreeCADGui/PySide not loaded).")

else:
    # -----------------------------------------------------------------------------
    # SELECTION -> BUILD123D SELECTOR HELPERS
    # -----------------------------------------------------------------------------
    def _round3(x):
        """
        Rounds a number to 3 decimal places for cleaner code generation.

        Args:
            x (float): The input number.

        Returns:
            float | int: The rounded value, or the original input on error.
        """
        try:
            return round(float(x), 3)
        except Exception:
            return x

    def selector_for_vertex(vertex_shape):
        """
        Generates build123d selector code for a specific vertex.

        Uses `sort_by_distance` with the vertex's coordinates.

        Args:
            vertex_shape (TopoDS_Vertex): The vertex geometry.

        Returns:
            str | None: The selector string (e.g., `part.vertices().sort_by_distance(...).first`).
        """
        try:
            p = vertex_shape.Point
            x, y, z = _round3(p.x), _round3(p.y), _round3(p.z)
            return f"part.vertices().sort_by_distance(({x}, {y}, {z})).first"
        except Exception:
            return None

    def selector_for_edge(edge_shape):
        """
        Generates build123d selector code for a specific edge.

        Uses `sort_by_distance` with the edge's center of mass.

        Args:
            edge_shape (TopoDS_Edge): The edge geometry.

        Returns:
            str | None: The selector string.
        """
        try:
            c = edge_shape.CenterOfMass
            x, y, z = _round3(c.x), _round3(c.y), _round3(c.z)
            return f"part.edges().sort_by_distance(({x}, {y}, {z})).first"
        except Exception:
            return None

    def selector_for_face(face_shape):
        """
        Generates build123d selector code for a specific face.

        Heuristics:
        1. If planar and aligned with X/Y/Z axes, uses `sort_by(Axis.X)`.
        2. Fallback to `sort_by_distance` using the face's center of mass.

        Args:
            face_shape (TopoDS_Face): The face geometry.

        Returns:
            str | None: The selector string.
        """
        try:
            c = face_shape.CenterOfMass
            cx, cy, cz = round(c.x, 2), round(c.y, 2), round(c.z, 2)

            uv = face_shape.Surface.parameter(c)
            n = face_shape.normalAt(uv[0], uv[1])

            if abs(n.z) > 0.99:
                return f"part.faces().sort_by(Axis.Z).{'last' if c.z > 0 else 'first'}"
            if abs(n.x) > 0.99:
                return f"part.faces().sort_by(Axis.X).{'last' if c.x > 0 else 'first'}"
            if abs(n.y) > 0.99:
                return f"part.faces().sort_by(Axis.Y).{'last' if c.y > 0 else 'first'}"

            return f"part.faces().sort_by_distance(({cx}, {cy}, {cz})).first"
        except Exception:
            return None

    def selector_from_subshape(subshape):
        """
        Dispatches selector generation based on the shape type (Vertex/Edge/Face).

        Args:
            subshape (TopoDS_Shape): The sub-object selected in FreeCAD.

        Returns:
            str | None: The generated selector code.
        """
        try:
            st = getattr(subshape, "ShapeType", None)
            if st == "Vertex":
                return selector_for_vertex(subshape)
            if st == "Edge":
                return selector_for_edge(subshape)
            if st == "Face":
                return selector_for_face(subshape)
            return None
        except Exception:
            return None

    # -----------------------------------------------------------------------------
    # WIDGET CLASSES
    # -----------------------------------------------------------------------------
    class ParameterWidget(QtGui.QWidget):
        """
        A single slider widget for the Tuner tab.

        Attributes:
            name (str): Variable name.
            parent_dock (B123dDockWidget): Reference to main dock.
        """
        def __init__(self, name, value, scale_limit, parent_dock):
            """
            Args:
                name (str): Variable name.
                value (float): Current value.
                scale_limit (float): Max range for the slider.
                parent_dock (B123dDockWidget): The parent widget.
            """
            super().__init__()
            self.name = name
            self.parent_dock = parent_dock
            self.scale_limit = scale_limit

            layout = QtGui.QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            self.lbl = QtGui.QLabel(f"{name}:")
            self.lbl.setFixedWidth(70)
            layout.addWidget(self.lbl)

            self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
            self.slider.setMinimum(0)
            self.slider.setMaximum(1000)
            self.slider.valueChanged.connect(self.on_slide)

            self.val_lbl = QtGui.QLabel(f"{value:.2f}")
            self.val_lbl.setFixedWidth(50)

            layout.addWidget(self.slider)
            layout.addWidget(self.val_lbl)
            self.setLayout(layout)

            self.update_state(value, self.scale_limit)

        def update_state(self, new_val, new_limit=None):
            if new_limit:
                self.scale_limit = new_limit
            self.val_lbl.setText(f"{new_val:.2f}")

            if not self.slider.isSliderDown():
                self.slider.blockSignals(True)
                if self.scale_limit and self.scale_limit > 0:
                    pos = int((new_val / self.scale_limit) * 1000)
                else:
                    pos = 500
                self.slider.setValue(max(0, min(1000, pos)))
                self.slider.blockSignals(False)

        def on_slide(self, val):
            if self.scale_limit:
                new_val = (val / 1000.0) * self.scale_limit
            else:
                new_val = float(val)
            self.val_lbl.setText(f"{new_val:.2f}")
            self.parent_dock.update_variable_from_slider(self.name, new_val)

    class B123dLiveSyncObserver:
        """
        FreeCAD Document Observer.
        
        Watches for object changes in the document to trigger GUI -> Code updates.
        """
        def __init__(self, panel):
            self.panel = panel

        def slotChangedObject(self, obj, prop):
            """
            Called by FreeCAD when an object property changes.

            Visibility changes are intentionally ignored. Users often hide/show the
            native object or shadow to visually compare them, and that should not
            rewrite the CodeCAD editor or alter the model/code sync state.
            """
            if self.panel.programmatic_update:
                return

            # Treat hide/show as viewport/debug behavior, not model-authoring behavior.
            #
            # Important: do NOT stop timer_gui_to_code here.
            # FreeCAD commands like Fillet/Chamfer create a real feature and also hide
            # the base object. If we cancel the queued GUI->Code update on that visibility
            # event, the new feature never gets transpiled into the editor.
            if prop == "Visibility":
                self.panel.note_visibility_change_ignored(obj)
                return

            if self.panel.gui_to_code_suppressed():
                return

            if obj.TypeId.startswith("Part::") and obj.Name != "Build123d_Shadow":
                self.panel.trigger_gui_to_code_update()

        def slotCreatedObject(self, obj):
            """
            Called by FreeCAD when a new object is added to the document.

            Args:
                obj (App.DocumentObject): The created object.
            """
            if self.panel.programmatic_update:
                return
            if self.panel.gui_to_code_suppressed():
                return
            self.panel.trigger_gui_to_code_update()

        def slotDeletedObject(self, obj):
            """
            Called by FreeCAD when an object is removed from the document.

            Args:
                obj (App.DocumentObject): The deleted object.
            """
            try:
                if self.panel.programmatic_update:
                    return
                if self.panel.gui_to_code_suppressed():
                    return
                self.panel.trigger_gui_to_code_update()
            except Exception:
                pass

    class B123dSelectionObserver:
        """
        FreeCAD Selection Observer.

        Monitors user selection in the 3D view to update the 'Insert Selector' UI helper.
        """
        def __init__(self, panel):
            self.panel = panel

        def addSelection(self, doc, obj_name, sub, pos):
            """
            Called when a user selects an object or sub-element in the 3D view.

            Args:
                doc (str): Name of the document.
                obj_name (str): Name of the selected object.
                sub (str): Sub-element name (e.g., "Face1").
                pos (tuple): 3D coordinates of the click.
            """
            try:
                if self.panel.programmatic_update:
                    return
                self.panel.update_selector_from_current_selection()
                self.panel.update_origin_button_label()
            except Exception:
                pass

        def removeSelection(self, doc, obj_name, sub):
            """
            Called when a user deselects an object.
            """
            try:
                if self.panel.programmatic_update:
                    return
                self.panel.update_selector_from_current_selection()
                self.panel.update_origin_button_label()
            except Exception:
                pass

        def clearSelection(self, doc):
            """
            Called when the user clears the entire selection (e.g., clicking background).
            """
            try:
                if self.panel.programmatic_update:
                    return
                self.panel.set_selector_text(None, hint="Select a face/edge/vertex…")
                self.panel.update_origin_button_label()
            except Exception:
                pass

        def setPreselection(self, doc, obj_name, sub):
            """
            Called on mouse-over (ignored).
            """
            pass

    # -----------------------------------------------------------------------------
    # MAIN DOCK
    # -----------------------------------------------------------------------------
    class B123dDockWidget(QtGui.QDockWidget):
        """
        The main Code-CAD Studio dock panel.

        Attributes:
            engine (SyncEngine): The logic engine instance.
            editor (QPlainTextEdit): The code editor widget.
            param_widgets (dict): Map of variable names to ParameterWidgets.
        """
        def __init__(self, parent=None):
            """
            Initializes the Dock Widget and sets up the UI layout.

            Args:
                parent (QWidget, optional): Parent widget. Defaults to None.
            """
            super().__init__(parent)
            self.setWindowTitle("Code-CAD Studio")
            self.resize(520, 750)

            # Engine (single backend used by both GUI and headless)
            self.engine = SyncEngine(FreeCADAPI())

            # IMPORTANT: prevents GUI->Code overwrite right after code application
            self._suppress_gui_to_code_until = 0.0

            main = QtGui.QWidget()
            self.setWidget(main)
            layout = QtGui.QVBoxLayout()
            main.setLayout(layout)

            self.tabs = QtGui.QTabWidget()
            layout.addWidget(self.tabs)

            # -------------------------
            # EDITOR TAB
            # -------------------------
            t1 = QtGui.QWidget()
            l1 = QtGui.QVBoxLayout()
            t1.setLayout(l1)

            self.editor = QtGui.QPlainTextEdit()
            self.editor.setFont(QtGui.QFont("Courier New", 10))
            l1.addWidget(self.editor)

            tools = QtGui.QGroupBox("Modeling Tools")
            tools_l = QtGui.QVBoxLayout()
            tools.setLayout(tools_l)

            self.sel_lbl = QtGui.QLabel("Select a face/edge/vertex…")
            self.sel_lbl.setStyleSheet("background: #eee; padding: 6px;")
            tools_l.addWidget(self.sel_lbl)
            
            # Shared code snippet buttons.
            # These mutate the editor text; the normal textChanged debounce then
            # applies code -> FreeCAD and updates the shadow.
            snippets_box = QtGui.QGroupBox("Insert Code")
            snippets_l = QtGui.QVBoxLayout()
            snippets_box.setLayout(snippets_l)

            # This controls which shared snippet variant is inserted:
            # - build123d: normal centered build123d-origin snippets
            # - FreeCAD: FreeCAD-origin snippets when a snippet provides freecad_code
            self.snippet_origin_mode = "b123d"

            origin_row = QtGui.QHBoxLayout()
            origin_row.addWidget(QtGui.QLabel("Snippet origin:"))

            self.btn_snippet_origin_b123d = QtGui.QPushButton("build123d")
            self.btn_snippet_origin_fc = QtGui.QPushButton("FreeCAD")

            self.btn_snippet_origin_b123d.setCheckable(True)
            self.btn_snippet_origin_fc.setCheckable(True)

            self.btn_snippet_origin_b123d.clicked.connect(
                lambda checked=False: self.set_snippet_origin_mode("b123d")
            )
            self.btn_snippet_origin_fc.clicked.connect(
                lambda checked=False: self.set_snippet_origin_mode("freecad")
            )

            origin_row.addWidget(self.btn_snippet_origin_b123d)
            origin_row.addWidget(self.btn_snippet_origin_fc)
            snippets_l.addLayout(origin_row)

            grouped = {}
            for snip in SNIPPETS:
                grouped.setdefault(snip.group, []).append(snip)

            for group_name, snippets in grouped.items():
                snippets_l.addWidget(QtGui.QLabel(group_name))

                row_l = QtGui.QHBoxLayout()
                for snip in snippets:
                    btn = QtGui.QPushButton(snip.label)
                    btn.clicked.connect(
                        lambda checked=False, s=snip: self.insert_code_snippet(
                            self.snippet_code_for_origin(s),
                            s.mode,
                        )
                    )
                    row_l.addWidget(btn)

                snippets_l.addLayout(row_l)

            self.set_snippet_origin_mode("b123d")

            tools_l.addWidget(snippets_box)

            row = QtGui.QHBoxLayout()
            self.btn_insert_selector = QtGui.QPushButton("Insert Selector")
            self.btn_insert_selector.setEnabled(False)
            self.btn_insert_selector.clicked.connect(self.insert_current_selector_at_cursor)

            self.btn_clear_selection = QtGui.QPushButton("Clear Selection")
            self.btn_clear_selection.clicked.connect(lambda: FreeCADGui.Selection.clearSelection())

            row.addWidget(self.btn_insert_selector)
            row.addWidget(self.btn_clear_selection)
            tools_l.addLayout(row)

            # Origin toggle button (single button)
            self.btn_origin_toggle = QtGui.QPushButton("Use build123d origin")
            self.btn_origin_toggle.clicked.connect(self.toggle_origin_for_tip)
            tools_l.addWidget(self.btn_origin_toggle)

            l1.addWidget(tools)

            self.status = QtGui.QLabel("Ready")
            self.status.setAlignment(QtCore.Qt.AlignCenter)
            self.status.setStyleSheet("background: #dfd; padding: 5px; color: green;")
            l1.addWidget(self.status)

            self.tabs.addTab(t1, "Editor")

            # -------------------------
            # FREECAD CMD TAB
            # -------------------------
            t_cmd = QtGui.QWidget()
            cmd_l = QtGui.QVBoxLayout()
            t_cmd.setLayout(cmd_l)

            self.fc_cmd_editor = QtGui.QPlainTextEdit()
            self.fc_cmd_editor.setReadOnly(True)
            self.fc_cmd_editor.setFont(QtGui.QFont("Courier New", 10))
            self.fc_cmd_editor.setPlainText(
                "# FreeCAD command trace will appear here after Code → GUI sync.\n"
            )
            cmd_l.addWidget(self.fc_cmd_editor)

            self.tabs.addTab(t_cmd, "FreeCAD Cmd")

            # -------------------------
            # TUNER TAB
            # -------------------------
            t2 = QtGui.QWidget()
            l2 = QtGui.QVBoxLayout()
            t2.setLayout(l2)

            l2.addWidget(QtGui.QLabel("Variables (Common Scale):"))
            self.pl = QtGui.QVBoxLayout()
            self.pl.setAlignment(QtCore.Qt.AlignTop)
            pc = QtGui.QWidget()
            pc.setLayout(self.pl)
            l2.addWidget(pc)

            self.tabs.addTab(t2, "Tuner")

            # -------------------------
            # VERIFICATION BAR
            # -------------------------
            self.verify_bar = QtGui.QLabel("UNVERIFIED")
            self.verify_bar.setAlignment(QtCore.Qt.AlignCenter)
            self.verify_bar.setFont(QtGui.QFont("Arial", 10, QtGui.QFont.Bold))
            self.verify_bar.setStyleSheet("background: #ccc; color: #555; padding: 8px;")
            layout.addWidget(self.verify_bar)

            # -------------------------
            # STATE
            # -------------------------
            self.param_widgets = {}
            self.programmatic_update = False
            self.current_selector_text = None

            # Debounce timers
            self.timer_gui_to_code = QtCore.QTimer()
            self.timer_gui_to_code.setSingleShot(True)
            self.timer_gui_to_code.timeout.connect(self.perform_gui_to_code)

            self.timer_code_to_gui = QtCore.QTimer()
            self.timer_code_to_gui.setSingleShot(True)
            self.timer_code_to_gui.timeout.connect(self.perform_code_to_gui)

            # Hooks
            self.editor.textChanged.connect(self.on_code_edited)

            self.observer = B123dLiveSyncObserver(self)
            FreeCAD.addDocumentObserver(self.observer)

            self.sel_obs = B123dSelectionObserver(self)
            FreeCADGui.Selection.addObserver(self.sel_obs)

            # Ensure shadow exists & populate editor from current GUI
            self.engine.ensure_shadow()
            self.perform_gui_to_code()
            self.update_selector_from_current_selection()
            self.update_origin_button_label()

        # -------------------------------------------------------------------------
        # Suppression helpers
        # -------------------------------------------------------------------------
        def gui_to_code_suppressed(self) -> bool:
            """
            Checks if the GUI -> Code sync is temporarily disabled.

            Returns:
                bool: True if suppressed.
            """
            return time.monotonic() < float(self._suppress_gui_to_code_until)

        def suppress_gui_to_code_for(self, seconds: float):
            """
            Temporarily disables FreeCAD -> Editor updates.

            Used to prevent an infinite loop where editing code triggers a recompute,
            which triggers the observer, which tries to rewrite the code.

            Args:
                seconds (float): Duration to suppress updates.
            """
            self._suppress_gui_to_code_until = time.monotonic() + float(seconds)

        def closeEvent(self, e):
            """
            Cleanup hook when the dock is closed.

            Removes document and selection observers to prevent memory leaks.

            Args:
                e (QCloseEvent): The close event.
            """
            try:
                FreeCAD.removeDocumentObserver(self.observer)
            except Exception:
                pass
            try:
                FreeCADGui.Selection.removeObserver(self.sel_obs)
            except Exception:
                pass
            super().closeEvent(e)
        
        def note_visibility_change_ignored(self, obj=None):
            """
            Ignore GUI -> Code sync caused directly by hiding/unhiding objects.

            Do not stop timer_gui_to_code here. Some real FreeCAD modeling commands
            such as Fillet/Chamfer also perform visibility changes as part of creating
            a feature chain. Any queued model update should still be allowed to run.
            """
            try:
                name = getattr(obj, "Name", "object")
                self.status.setText(f"Visibility changed for {name}; ignored")
                self.status.setStyleSheet("background: #eee; color: #555; padding: 5px;")
            except Exception:
                pass

        # -------------------------------------------------------------------------
        # Clear panel + make shadow blank (engine-only for shadow ops)
        # -------------------------------------------------------------------------
        def clear_panel_no_part(self):
            """Called when there are no non-shadow Part:: objects in the document."""
            self.programmatic_update = True
            try:
                # Clear editor
                self.editor.blockSignals(True)
                try:
                    self.editor.setPlainText("")
                finally:
                    self.editor.blockSignals(False)

                # Clear tuner widgets
                for name in list(self.param_widgets.keys()):
                    try:
                        self.param_widgets[name].deleteLater()
                    except Exception:
                        pass
                    del self.param_widgets[name]

                # Reset selector UI
                self.set_selector_text(None, hint="No part in document. Create a Part:: object…")

                # Reset status + verify bar
                self.status.setText("No Part")
                self.status.setStyleSheet("background: #eee; color: #555; padding: 5px;")
                self.verify_bar.setText("NO PART")
                self.verify_bar.setStyleSheet("background: #ccc; color: #555; padding: 8px;")

                # Button label
                self.btn_origin_toggle.setText("Use build123d origin")
                self.btn_origin_toggle.setEnabled(False)

                # Remove shadow via engine (no ViewObject touches)
                self.engine.remove_shadow()

                # Recompute
                self.engine.api.recompute()

            finally:
                self.programmatic_update = False

        # -------------------------------------------------------------------------
        # GUI -> CODE
        # -------------------------------------------------------------------------
        def trigger_gui_to_code_update(self):
            """
            Starts the debounce timer to read FreeCAD state and update the editor.
            """
            if self.gui_to_code_suppressed():
                return
            self.status.setText("Reading FreeCAD…")
            self.status.setStyleSheet("background: #ddf; color: blue; padding: 5px;")
            self.timer_gui_to_code.start(300)

        def find_tip_object(self):
            """
            Delegates to the engine to find the current tip object.

            Returns:
                App.DocumentObject | None: The tip object.
            """
            return self.engine.find_tip_object()

        def perform_gui_to_code(self):
            """
            Triggered when the user changes a FreeCAD object (e.g., via Property View).
            Calls the Transpiler to update the text editor.
            """
            if self.gui_to_code_suppressed():
                return

            tip = self.find_tip_object()
            if not tip:
                self.clear_panel_no_part()
                return

            try:
                code = self.engine.code_from_tip(tip)

                # Update editor (this is the destructive part, so only do it for true GUI edits)
                self.programmatic_update = True
                try:
                    self.editor.blockSignals(True)
                    try:
                        self.editor.setPlainText(code)
                    finally:
                        self.editor.blockSignals(False)
                finally:
                    self.programmatic_update = False

                # Update shadow only (no injection)
                self.engine.update_shadow_code(code)

                self.status.setText("Synced (GUI → Code)")
                self.status.setStyleSheet("background: #dfd; color: green; padding: 5px;")

                QtCore.QTimer.singleShot(120, self.deferred_verification)

                self.refresh_tuner_ui()
                self.update_origin_button_label()

            except Exception as e:
                self.status.setText(f"Transpile Error: {e}")
                self.status.setStyleSheet("background: #fdd; color: red; padding: 5px;")

        # -------------------------------------------------------------------------
        # CODE -> GUI
        # -------------------------------------------------------------------------
        def on_code_edited(self):
            """
            Qt Slot called whenever the text in the editor changes.
            Starts the debounce timer for Code -> GUI sync.
            """
            if self.programmatic_update:
                return
            self.status.setText("Writing…")
            self.status.setStyleSheet("background: #fff4cc; color: orange; padding: 5px;")
            self.timer_code_to_gui.start(800)
            self.refresh_tuner_ui()

        def perform_code_to_gui(self):
            """
            Triggered when the user types in the editor.
            Calls the Engine -> Parser to update FreeCAD objects.
            """
            code = self.editor.toPlainText()

            # CRITICAL:
            # Prevent the observer from immediately triggering GUI->Code transpile,
            # which would inline numbers and erase user variables.
            self.suppress_gui_to_code_for(1.0)

            self.programmatic_update = True
            try:
                result = self.engine.apply_pipeline(code, make_shadow=True, verify=False)
                self.update_fc_cmd_view(result.get("freecad_code") or result.get("trace"))
            finally:
                # keep programmatic_update true a moment longer in case FreeCAD fires late change notifications
                QtCore.QTimer.singleShot(250, self._end_programmatic_update)

            if not result.get("ok", False):
                msg = result.get("message", "Error")
                self.status.setText(msg)
                self.status.setStyleSheet("background: #fdd; color: red; padding: 5px;")
            else:
                msg = result.get("message", "Applied")
                self.status.setText(msg)
                self.status.setStyleSheet("background: #dfd; color: green; padding: 5px;")

            QtCore.QTimer.singleShot(120, self.deferred_verification)

            self.refresh_tuner_ui()
            self.update_origin_button_label()

        def _end_programmatic_update(self):
            """
            Callback to reset the `programmatic_update` flag after a delay.
            """
            self.programmatic_update = False

        # -------------------------------------------------------------------------
        # Verification (deferred)
        # -------------------------------------------------------------------------
        def deferred_verification(self):
            """
            Runs after an update to compare the FreeCAD object and Shadow object.
            Updates the UI label to "MATCH CONFIRMED" (Green) or "MISMATCH" (Red).
            """
            try:
                self.engine.api.recompute()
            except Exception:
                return

            tip = self.engine.find_tip_object()
            shadow = self.engine.get_shadow_object()

            if not tip:
                self.verify_bar.setText("NO PART")
                self.verify_bar.setStyleSheet("background: #ccc; color: #555; padding: 8px;")
                return

            if not shadow:
                self.verify_bar.setText("NO SHADOW")
                self.verify_bar.setStyleSheet("background: #ccc; color: #555; padding: 8px;")
                return

            ok, reason = self.engine.verify(tip, shadow)
            if ok:
                self.verify_bar.setText("MATCH CONFIRMED")
                self.verify_bar.setStyleSheet(
                    "background: #dfd; color: green; padding: 8px; border: 2px solid green;"
                )
            else:
                self.verify_bar.setText(f"MISMATCH: {reason}")
                self.verify_bar.setStyleSheet(
                    "background: #fdd; color: red; padding: 8px; border: 2px solid red;"
                )

        # -------------------------------------------------------------------------
        # TUNER LOGIC
        # -------------------------------------------------------------------------
        def refresh_tuner_ui(self):
            """
            Parses variables from the current code and rebuilds the Tuner sliders.
            """
            current_vars = self.engine.parse_variables(self.editor.toPlainText())
            current_names = set(v["name"] for v in current_vars)
            vals = [v["value"] for v in current_vars]

            if not vals:
                for name in list(self.param_widgets.keys()):
                    try:
                        self.param_widgets[name].deleteLater()
                    except Exception:
                        pass
                    del self.param_widgets[name]
                return

            max_val = max(vals)
            min_val = min(vals)

            use_common_scale = True
            if min_val > 0 and (max_val / min_val > 100):
                use_common_scale = False

            scale_limit = max_val * 1.5 if use_common_scale else None

            for name in list(self.param_widgets.keys()):
                if name not in current_names:
                    self.param_widgets[name].deleteLater()
                    del self.param_widgets[name]

            for v in current_vars:
                name = v["name"]
                val = v["value"]
                this_limit = scale_limit if scale_limit else (val * 2.0 if val != 0 else 1.0)

                if name in self.param_widgets:
                    self.param_widgets[name].update_state(val, this_limit)
                else:
                    w = ParameterWidget(name, val, this_limit, self)
                    self.pl.addWidget(w)
                    self.param_widgets[name] = w

        def update_variable_from_slider(self, name, val):
            """
            Called when a slider moves. Regex-replaces the variable in the editor.

            Args:
                name (str): Variable name.
                val (float): New value.
            """
            code = self.editor.toPlainText()
            if not code.strip():
                return

            lines = code.split("\n")
            pattern = re.compile(rf"^({re.escape(name)})\s*=\s*([-+]?[0-9]*\.?[0-9]+)(.*)$")

            new_lines = []
            for line in lines:
                m = pattern.match(line.strip())
                if m:
                    new_lines.append(f"{name} = {val:.2f}{m.group(3)}")
                else:
                    new_lines.append(line)

            new_code = "\n".join(new_lines)

            self.programmatic_update = True
            try:
                self.editor.blockSignals(True)
                try:
                    self.editor.setPlainText(new_code)
                finally:
                    self.editor.blockSignals(False)
            finally:
                self.programmatic_update = False

            # Apply to FreeCAD + shadow via engine
            self.perform_code_to_gui()
            self.refresh_tuner_ui()

        # -------------------------------------------------------------------------
        # Selector insertion (button-driven)
        # -------------------------------------------------------------------------
        def set_selector_text(self, text, hint=None):
            """
            Updates the selector helper UI label and button state.

            Args:
                text (str | None): The generated selector code, or None if invalid.
                hint (str, optional): Message to display if text is None.
            """
            self.current_selector_text = text
            if text:
                self.sel_lbl.setText(text)
                self.sel_lbl.setStyleSheet("background: #ddf; color: #003399; padding: 6px;")
                self.btn_insert_selector.setEnabled(True)
            else:
                self.sel_lbl.setText(hint or "Selection unsupported/complex")
                self.sel_lbl.setStyleSheet("background: #f5f5f5; color: #666; padding: 6px;")
                self.btn_insert_selector.setEnabled(False)

        def update_selector_from_current_selection(self):
            """
            Polls the current FreeCAD selection state and generates selector code.
            Updates the "Insert Selector" UI area.
            """
            if not self.find_tip_object():
                self.set_selector_text(None, hint="No part in document. Create a Part:: object…")
                return

            try:
                sel = FreeCADGui.Selection.getSelectionEx()
                if not sel:
                    self.set_selector_text(None, hint="Select a face/edge/vertex…")
                    return

                s0 = sel[0]
                if not s0.SubElementNames:
                    self.set_selector_text(None, hint="Select a face/edge/vertex…")
                    return

                obj = s0.Object
                subname = s0.SubElementNames[0]
                subshape = obj.getSubObject(subname)
                if not subshape:
                    self.set_selector_text(None, hint="Selection unsupported/complex")
                    return

                code = selector_from_subshape(subshape)
                if not code:
                    self.set_selector_text(None, hint="Selection unsupported/complex")
                    return

                self.set_selector_text(code)
            except Exception:
                self.set_selector_text(None, hint="Selection unsupported/complex")

        def insert_current_selector_at_cursor(self):
            """
            Inserts the generated selector code into the text editor at the current cursor position.
            """
            if not self.current_selector_text:
                return

            cursor = self.editor.textCursor()
            cursor.insertText(self.current_selector_text)

            # Apply pipeline
            self.perform_code_to_gui()
            self.refresh_tuner_ui()
        
        def set_snippet_origin_mode(self, mode: str):
            """
            Selects which shared snippet variant the local toolbar inserts.

            This is separate from the existing origin toggle for the current
            FreeCAD object. This only affects future snippet button inserts.
            """
            self.snippet_origin_mode = "freecad" if mode == "freecad" else "b123d"

            try:
                use_b123d = self.snippet_origin_mode == "b123d"

                self.btn_snippet_origin_b123d.setChecked(use_b123d)
                self.btn_snippet_origin_fc.setChecked(not use_b123d)

                # Leave both clickable, but visually mark the active one.
                self.btn_snippet_origin_b123d.setStyleSheet(
                    "font-weight: bold;" if use_b123d else ""
                )
                self.btn_snippet_origin_fc.setStyleSheet(
                    "font-weight: bold;" if not use_b123d else ""
                )
            except Exception:
                pass

        def snippet_code_for_origin(self, snip):
            """
            Returns the snippet code variant for the current snippet origin mode.
            """
            if self.snippet_origin_mode == "freecad":
                fc_code = getattr(snip, "freecad_code", None)
                if fc_code:
                    return fc_code

            return snip.code

        def insert_code_snippet(self, code: str, mode: str = "append"):
            """
            Inserts or replaces editor code using a shared CodeSnippet.

            Append-mode snippets always go at the bottom of the editor so users can
            build a linear operation chain like:
                primitive -> fillet -> transform
            without manually moving the cursor after every button click.
            """
            if mode == "replace":
                self.editor.setPlainText(code.rstrip() + "\n")
                self._move_editor_cursor_to_bottom()
                return

            current = self.editor.toPlainText().rstrip()
            snippet = code.strip("\n")

            if current:
                new_text = current + "\n\n" + snippet + "\n"
            else:
                new_text = snippet + "\n"

            self.editor.setPlainText(new_text)
            self._move_editor_cursor_to_bottom()

        def _move_editor_cursor_to_bottom(self):
            """
            Move editor cursor to the end of the document.
            """
            cursor = self.editor.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            self.editor.setTextCursor(cursor)
            self.editor.setFocus()
        # -------------------------------------------------------------------------
        # Origin Toggle (delegates to engine)
        # -------------------------------------------------------------------------
        def update_origin_button_label(self):
            """
            Checks the engine state for the current tip and updates the Origin Toggle button text.
            """
            tip = self.find_tip_object()
            root, using = self.engine.get_origin_state(tip)
            if not root:
                self.btn_origin_toggle.setText("Use build123d origin")
                self.btn_origin_toggle.setEnabled(False)
                return

            self.btn_origin_toggle.setEnabled(True)
            self.btn_origin_toggle.setText("Use FreeCAD origin" if using else "Use build123d origin")

        def toggle_origin_for_tip(self):
            """
            Handler for the 'Use build123d/FreeCAD origin' button.
            """
            tip = self.find_tip_object()
            if not tip:
                return

            self.programmatic_update = True
            try:
                ok, msg, using = self.engine.toggle_origin_for_tip(tip)
                if ok:
                    self.status.setText(msg)
                    self.status.setStyleSheet("background: #ddf; color: blue; padding: 5px;")
                else:
                    self.status.setText(msg)
                    self.status.setStyleSheet("background: #fdd; color: red; padding: 5px;")
            finally:
                self.programmatic_update = False

            # This WAS the other way variables got wiped: toggling origin changes the model,
            # which triggers GUI->Code. That's fine here because origin toggle is a GUI-driven change.
            self.perform_gui_to_code()
            self.update_origin_button_label()
        
        def update_fc_cmd_view(self, text: str | None):
            """
            Updates the read-only FreeCAD command trace tab.
            """
            try:
                if not text:
                    text = "# No FreeCAD command trace available.\n"

                self.fc_cmd_editor.blockSignals(True)
                try:
                    self.fc_cmd_editor.setPlainText(text)
                finally:
                    self.fc_cmd_editor.blockSignals(False)
            except Exception:
                pass

    # -----------------------------------------------------------------------------
    # WORKBENCH LAUNCHER
    # -----------------------------------------------------------------------------
    _panel_instance = None

    def create_panel():
        """
        Creates and shows the Dock Widget.

        Returns:
            B123dDockWidget: The created or existing instance.
        """
        global _panel_instance
        mw = FreeCADGui.getMainWindow()

        if _panel_instance:
            try:
                _panel_instance.show()
                return _panel_instance
            except Exception:
                _panel_instance = None

        _panel_instance = B123dDockWidget(mw)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel_instance)
        _panel_instance.show()
        return _panel_instance

    def toggle_panel():
        """
        Toggles the visibility of the Code-CAD Studio dock widget.
        If the widget does not exist, it creates it.
        """
        global _panel_instance
        if _panel_instance and _panel_instance.isVisible():
            _panel_instance.hide()
        else:
            create_panel()