from PySide import QtGui, QtCore
import FreeCAD
import FreeCADGui

# Import logic from core
from core.transpiler import transpile_object
from core.parser import inject_code_to_freecad, parse_variables
from core.verifier import compare_shapes
from core.shadow import ensure_shadow_object, Build123dShadow, Build123dViewProvider

# -----------------------------------------------------------------------------
# WIDGET CLASSES
# -----------------------------------------------------------------------------
class ParameterWidget(QtGui.QWidget):
    def __init__(self, name, value, scale_limit, parent_dock):
        super().__init__()
        self.name = name; self.parent_dock = parent_dock
        self.scale_limit = scale_limit
        
        layout = QtGui.QHBoxLayout(); layout.setContentsMargins(0,0,0,0)
        self.lbl = QtGui.QLabel(f"{name}:"); self.lbl.setFixedWidth(70); layout.addWidget(self.lbl)
        
        self.slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(0); self.slider.setMaximum(1000) 
        self.slider.valueChanged.connect(self.on_slide)
        
        self.val_lbl = QtGui.QLabel(f"{value:.2f}"); self.val_lbl.setFixedWidth(50)
        layout.addWidget(self.slider); layout.addWidget(self.val_lbl)
        self.setLayout(layout)
        
        self.update_state(value, self.scale_limit)

    def update_state(self, new_val, new_limit=None):
        if new_limit: self.scale_limit = new_limit
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
            new_val = val
        self.val_lbl.setText(f"{new_val:.2f}")
        self.parent_dock.update_variable_from_slider(self.name, new_val)

class B123dLiveSyncObserver:
    def __init__(self, panel): self.panel = panel
    def slotChangedObject(self, obj, prop):
        if self.panel.programmatic_update: return
        # Ignore our own Shadow object to prevent loops
        if obj.TypeId.startswith("Part::") and obj.Name != "Build123d_Shadow":
            self.panel.trigger_gui_to_code_update()
            
    def slotCreatedObject(self, obj):
        if self.panel.programmatic_update: return
        self.panel.trigger_gui_to_code_update()

class B123dDockWidget(QtGui.QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Code-CAD Studio")
        self.resize(500, 700)
        main = QtGui.QWidget(); self.setWidget(main); layout = QtGui.QVBoxLayout(); main.setLayout(layout)
        self.tabs = QtGui.QTabWidget(); layout.addWidget(self.tabs)
        
        # EDITOR TAB
        t1 = QtGui.QWidget(); l1 = QtGui.QVBoxLayout(); t1.setLayout(l1)
        self.editor = QtGui.QPlainTextEdit(); self.editor.setFont(QtGui.QFont("Courier New", 10)); l1.addWidget(self.editor)
        self.status = QtGui.QLabel("Ready"); self.status.setAlignment(QtCore.Qt.AlignCenter); self.status.setStyleSheet("background: #dfd; padding: 5px; color: green;"); l1.addWidget(self.status)
        self.tabs.addTab(t1, "Editor")

        # TUNER TAB
        t2 = QtGui.QWidget(); l2 = QtGui.QVBoxLayout(); t2.setLayout(l2)
        l2.addWidget(QtGui.QLabel("Variables (Common Scale):"))
        self.pl = QtGui.QVBoxLayout(); self.pl.setAlignment(QtCore.Qt.AlignTop)
        pc = QtGui.QWidget(); pc.setLayout(self.pl); l2.addWidget(pc)
        self.tabs.addTab(t2, "Tuner")
        
        # VERIFICATION BAR
        self.verify_bar = QtGui.QLabel("UNVERIFIED")
        self.verify_bar.setAlignment(QtCore.Qt.AlignCenter); self.verify_bar.setFont(QtGui.QFont("Arial", 10, QtGui.QFont.Bold))
        self.verify_bar.setStyleSheet("background: #ccc; color: #555; padding: 8px;")
        layout.addWidget(self.verify_bar)

        self.param_widgets = {} 
        self.programmatic_update = False  
        
        # INCREASED DEBOUNCE TIME (200ms -> 800ms) to let you finish typing/clicking
        self.timer_gui_to_code = QtCore.QTimer(); self.timer_gui_to_code.setSingleShot(True); self.timer_gui_to_code.timeout.connect(self.perform_gui_to_code)
        self.timer_code_to_gui = QtCore.QTimer(); self.timer_code_to_gui.setSingleShot(True); self.timer_code_to_gui.timeout.connect(self.perform_code_to_gui)
        
        self.editor.textChanged.connect(self.on_code_edited)
        self.observer = B123dLiveSyncObserver(self); FreeCAD.addDocumentObserver(self.observer)
        ensure_shadow_object(); self.perform_gui_to_code()

    def closeEvent(self, e): FreeCAD.removeDocumentObserver(self.observer); super().closeEvent(e)
    
    def find_tip_object(self):
        doc = FreeCAD.ActiveDocument; 
        if not doc: return None
        candidates = set()
        for obj in doc.Objects:
            if obj.Name != "Build123d_Shadow" and obj.TypeId.startswith("Part::"): candidates.add(obj)
        parents = set()
        for obj in candidates:
            if hasattr(obj, "Base"):
                if isinstance(obj.Base, (list, tuple)):
                    for i in obj.Base: 
                        if hasattr(i, "Name"): parents.add(i)
                else: parents.add(obj.Base)
            if hasattr(obj, "EdgeLinks") and isinstance(obj.EdgeLinks, tuple) and len(obj.EdgeLinks)>0:
                 if hasattr(obj.EdgeLinks[0], "Name"): parents.add(obj.EdgeLinks[0])
        leaves = [c for c in candidates if c not in parents]
        return leaves[-1] if leaves else None

    # PATH A: GUI -> CODE
    def trigger_gui_to_code_update(self): 
        self.status.setText("Reading FreeCAD..."); self.status.setStyleSheet("background: #ddf; color: blue;")
        # Increased delay prevents freezing during rapid changes
        self.timer_gui_to_code.start(800)

    def perform_gui_to_code(self):
        tip = self.find_tip_object()
        if not tip: return
        
        # LOCK: Prevent observer from seeing these changes
        self.programmatic_update = True
        self.editor.blockSignals(True)
        try:
            code = "from build123d import *\n\n" + transpile_object(tip)
            self.editor.setPlainText(code)
            
            shadow = ensure_shadow_object()
            if shadow: 
                shadow.Code = code
                shadow.touch()
                # DO NOT RECOMPUTE HERE.
                # Scheduling verification for the next event loop prevents "Recursive Recompute"
                QtCore.QTimer.singleShot(200, self.deferred_verification)
            
            self.refresh_tuner_ui()
            self.status.setText("Synced (GUI -> Code)"); self.status.setStyleSheet("background: #dfd; color: green;")
        except Exception as e: 
            self.status.setText(f"Transpile Error: {e}"); self.status.setStyleSheet("background: #fdd; color: red;")
        finally: 
            self.editor.blockSignals(False)
            self.programmatic_update = False

    def deferred_verification(self):
        """Runs verify only when safe"""
        try:
            FreeCAD.ActiveDocument.recompute()
            tip = self.find_tip_object()
            shadow = ensure_shadow_object()
            self.run_verification(tip, shadow)
        except Exception:
            pass # Ignore recompute errors if document is busy

    # PATH B: CODE -> GUI
    def on_code_edited(self):
        if self.programmatic_update: return
        self.status.setText("Writing..."); self.status.setStyleSheet("background: #fff4cc; color: orange;"); self.timer_code_to_gui.start(800)
        self.refresh_tuner_ui()

    def perform_code_to_gui(self):
        code = self.editor.toPlainText()
        self.programmatic_update = True
        try:
            success, msg = inject_code_to_freecad(code)
            
            # Defer the shadow update to avoid locking the UI during typing
            if success or msg != "Syntax Error":
                shadow = ensure_shadow_object()
                if shadow: 
                    shadow.Code = code; shadow.touch()
                    QtCore.QTimer.singleShot(100, self.deferred_verification)

            if msg == "Syntax Error":
                self.status.setText("Syntax Error"); self.status.setStyleSheet("background: #fdd; color: red;")
            elif msg.startswith("Runtime Error"):
                self.status.setText(msg); self.status.setStyleSheet("background: #fdd; color: red;")
            else:
                self.status.setText(msg); self.status.setStyleSheet("background: #dfd; color: green;")
        except Exception as e:
            self.status.setText(f"Error: {e}"); self.status.setStyleSheet("background: #fdd; color: red;")
        finally: self.programmatic_update = False

    def run_verification(self, tip, shadow):
        if not tip or not shadow: return
        success, reason = compare_shapes(tip, shadow)
        if success:
            self.verify_bar.setText(f"MATCH CONFIRMED")
            self.verify_bar.setStyleSheet("background: #dfd; color: green; padding: 8px; border: 2px solid green;")
        else:
            self.verify_bar.setText(f"MISMATCH: {reason}")
            self.verify_bar.setStyleSheet("background: #fdd; color: red; padding: 8px; border: 2px solid red;")

    # TUNER LOGIC
    def refresh_tuner_ui(self):
        current_vars = parse_variables(self.editor.toPlainText())
        current_names = set(v['name'] for v in current_vars)
        vals = [v['value'] for v in current_vars]
        if not vals: return
        
        max_val = max(vals); min_val = min(vals)
        use_common_scale = True
        if min_val > 0 and (max_val / min_val > 100): use_common_scale = False
        scale_limit = max_val * 1.5 if use_common_scale else None

        for name in list(self.param_widgets.keys()):
            if name not in current_names: self.param_widgets[name].deleteLater(); del self.param_widgets[name]
        
        for v in current_vars:
            name = v['name']; val = v['value']
            this_limit = scale_limit if scale_limit else val * 2.0
            if name in self.param_widgets: self.param_widgets[name].update_state(val, this_limit)
            else:
                w = ParameterWidget(name, val, this_limit, self)
                self.pl.addWidget(w); self.param_widgets[name] = w

    def update_variable_from_slider(self, name, val):
        code = self.editor.toPlainText()
        lines = code.split('\n')
        pattern = re.compile(rf"^({name})\s*=\s*([-+]?[0-9]*\.?[0-9]+)(.*)$")
        new_lines = []
        for line in lines:
            match = pattern.match(line.strip())
            if match: new_lines.append(f"{name} = {val:.2f}{match.group(3)}")
            else: new_lines.append(line)
        new_code = '\n'.join(new_lines)
        
        self.programmatic_update = True 
        self.editor.blockSignals(True)
        self.editor.setPlainText(new_code)
        self.editor.blockSignals(False)
        
        try:
            inject_code_to_freecad(new_code)
            shadow = ensure_shadow_object()
            if shadow: 
                shadow.Code = new_code; shadow.touch()
                QtCore.QTimer.singleShot(50, self.deferred_verification)
        finally: 
            self.programmatic_update = False

# -----------------------------------------------------------------------------
# WORKBENCH LAUNCHER
# -----------------------------------------------------------------------------
_panel_instance = None

def create_panel():
    global _panel_instance
    mw = FreeCADGui.getMainWindow()
    if _panel_instance:
        try:
            _panel_instance.show()
            return _panel_instance
        except:
            _panel_instance = None # Handle deleted widgets
            
    _panel_instance = B123dDockWidget(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel_instance)
    _panel_instance.show()
    return _panel_instance

def toggle_panel():
    global _panel_instance
    if _panel_instance and _panel_instance.isVisible():
        _panel_instance.hide()
    else:
        create_panel()