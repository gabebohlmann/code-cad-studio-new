# cli/run.py

from __future__ import annotations

import os
import sys
import shlex
import argparse
import traceback

import FreeCAD


# -----------------------------------------------------------------------------
# stdout/stderr reliability in FreeCADCmd
# -----------------------------------------------------------------------------
def _linebuf():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass


def _normalize_path(p: str) -> str:
    # FreeCAD exporters are happier with forward slashes (and it avoids backslash issues)
    return os.path.abspath(p).replace("\\", "/")


# -----------------------------------------------------------------------------
# Discover script args robustly (FreeCADCmd varies by version/platform)
# -----------------------------------------------------------------------------
def _split_maybe_one_string(args: list[str]) -> list[str]:
    # If everything arrived as a single big string, split it like a shell would.
    if len(args) == 1 and isinstance(args[0], str) and "--" in args[0]:
        # posix=False is critical on Windows so backslashes are not treated as escapes
        return shlex.split(args[0], posix=False)
    return args


def _strip_placeholder(args: list[str]) -> list[str]:
    # Many people do: --pass _ <scriptargs...>
    if args and args[0] in ("_", "--", "PASS", "pass"):
        return args[1:]
    return args


def _collect_script_argv() -> list[str]:
    """
    Try to locate the arguments intended for this script.

    We attempt these in order:
      1) tokens after '--pass' in sys.argv
      2) tokens after '--' in sys.argv (if FreeCADCmd supports it)
      3) sys.argv[1:] as-is
      4) environment variable CODECAD_ARGS (last resort)
    """
    raw = list(sys.argv[1:])

    # Case 1: arguments after --pass
    if "--pass" in raw:
        i = raw.index("--pass")
        tail = raw[i + 1 :]
        tail = _split_maybe_one_string(tail)
        tail = _strip_placeholder(tail)
        return tail

    # Case 2: arguments after --
    if "--" in raw:
        i = raw.index("--")
        tail = raw[i + 1 :]
        tail = _split_maybe_one_string(tail)
        return tail

    # Case 3: try as-is (some builds already pass args directly)
    raw2 = _split_maybe_one_string(raw)
    raw2 = _strip_placeholder(raw2)
    if any(a.startswith("--code") or a.startswith("--out") for a in raw2):
        return raw2

    # Case 4: environment variable fallback
    env = os.environ.get("CODECAD_ARGS", "").strip()
    if env:
        return shlex.split(env, posix=False)

    return []


def _add_mod_root_to_syspath() -> str:
    # This file: <ModRoot>/cli/run.py
    mod_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if mod_root not in sys.path:
        sys.path.insert(0, mod_root)
    return mod_root


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# -----------------------------------------------------------------------------
# Export helpers
# -----------------------------------------------------------------------------
def _export_targets(doc):
    # Export only real shape-bearing objects; exclude the shadow
    out = []
    for o in getattr(doc, "Objects", []):
        if getattr(o, "Name", "") == "Build123d_Shadow":
            continue
        shp = getattr(o, "Shape", None)
        if shp is None:
            continue
        try:
            if shp.isNull():
                continue
        except Exception:
            pass
        out.append(o)
    return out


def _export_step(doc, out_path: str):
    out_path = _normalize_path(out_path)
    objs = _export_targets(doc)
    if not objs:
        return False, "STEP export: no shape-bearing objects found"

    # Prefer Import (works headless); ImportGui is GUI-only.
    try:
        import Import  # type: ignore

        Import.export(objs, out_path)
        return True, f"Exported STEP: {out_path}"
    except Exception as e:
        return False, f"STEP export failed via Import.export: {e}"


def _export_brep(doc, out_path: str):
    out_path = _normalize_path(out_path)
    objs = _export_targets(doc)
    if not objs:
        return False, "BREP export: no shape-bearing objects found"

    try:
        import Part  # type: ignore

        shapes = []
        for o in objs:
            shp = getattr(o, "Shape", None)
            if shp is not None:
                shapes.append(shp)

        if not shapes:
            return False, "BREP export: no shapes collected"

        comp = Part.Compound(shapes)
        comp.exportBrep(out_path)
        return True, f"Exported BREP: {out_path}"
    except Exception as e:
        return False, f"BREP export failed: {e}"


def _save_fcstd(doc, out_path: str):
    out_path = _normalize_path(out_path)
    try:
        # saveAs should work in FreeCADCmd, but we guard anyway
        doc.saveAs(out_path)
        return True, f"Saved FCStd: {out_path}"
    except Exception as e1:
        try:
            doc.saveCopy(out_path)
            return True, f"Saved FCStd (saveCopy): {out_path}"
        except Exception as e2:
            return False, f"FCStd save failed: {e1} / {e2}"


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    _linebuf()

    # Always print sys.argv so we can SEE what FreeCADCmd is actually passing
    print("[CodeCADStudio] sys.argv =", sys.argv, flush=True)

    argv = _collect_script_argv()
    print("[CodeCADStudio] script argv =", argv, flush=True)

    parser = argparse.ArgumentParser(prog="code-cad-studio")
    parser.add_argument("--code", required=True, help="Path to build123d python file")
    parser.add_argument("--out", required=False, help="Output file (.FCStd or .step/.stp)")
    parser.add_argument("--brep", required=False, help="Optional BREP output path (.brep)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    mod_root = _add_mod_root_to_syspath()

    code_path = _normalize_path(args.code)
    out_path = _normalize_path(args.out) if args.out else None
    brep_path = _normalize_path(args.brep) if args.brep else None

    if args.verbose:
        print("[CodeCADStudio] Mod root:", mod_root, flush=True)
        print("[CodeCADStudio] code    :", code_path, flush=True)
        print("[CodeCADStudio] out     :", out_path, flush=True)
        print("[CodeCADStudio] brep    :", brep_path, flush=True)

    if not os.path.exists(code_path):
        print(f"[CodeCADStudio] ERROR: code file not found: {code_path}", flush=True)
        return 2

    try:
        from core.engine import SyncEngine
        from core.freecad_api import FreeCADAPI
    except Exception:
        print("[CodeCADStudio] ERROR: failed to import core.* (sys.path issue?)", flush=True)
        traceback.print_exc()
        return 3

    # Create fresh document
    doc = FreeCAD.newDocument("CodeCADStudio_CLI")
    FreeCAD.setActiveDocument(doc.Name)

    engine = SyncEngine(FreeCADAPI())

    try:
        code = _read_text(code_path)

        result = engine.apply_pipeline(code, make_shadow=True, verify=False)
        if not result.get("ok", False):
            print("[CodeCADStudio] APPLY FAILED:", result.get("message"), flush=True)
            return 4

        print("[CodeCADStudio] APPLY OK:", result.get("message"), flush=True)

        # Recompute before exports
        try:
            doc.recompute()
        except Exception:
            pass

        if out_path:
            low = out_path.lower()
            if low.endswith(".fcstd"):
                ok, msg = _save_fcstd(doc, out_path)
                print("[CodeCADStudio]", msg, flush=True)
                if not ok:
                    return 5
            elif low.endswith((".step", ".stp")):
                ok, msg = _export_step(doc, out_path)
                print("[CodeCADStudio]", msg, flush=True)
                if not ok:
                    return 6
            else:
                print("[CodeCADStudio] WARNING: --out extension not recognized:", out_path, flush=True)

        if brep_path:
            ok, msg = _export_brep(doc, brep_path)
            print("[CodeCADStudio]", msg, flush=True)
            if not ok:
                return 7

        return 0

    except SystemExit:
        # argparse uses SystemExit; re-raise so FreeCADCmd shows help and exits nonzero
        raise
    except Exception:
        print("[CodeCADStudio] ERROR: unhandled exception", flush=True)
        traceback.print_exc()
        return 10


# FreeCAD often executes scripts with exec() in a context where __name__ may not be "__main__".
# Running main() unconditionally here makes this file behave like a CLI tool reliably in FreeCADCmd.
exit_code = main()
try:
    sys.exit(exit_code)
except Exception:
    pass
