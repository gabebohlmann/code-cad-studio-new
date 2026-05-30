# core/snippets.py

"""
Shared code snippets for Code-CAD Studio editor toolbars.

This module must stay GUI/server agnostic:
- no FreeCAD imports
- no PySide imports
- no FastAPI imports

The FreeCAD dock can import this directly.
The web server can expose it as JSON for the browser UI.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal


SnippetMode = Literal["replace", "append"]


@dataclass(frozen=True)
class CodeSnippet:
    """
    A reusable editor snippet.

    Attributes:
        key: Stable machine-readable identifier.
        label: Button label shown in GUI/web.
        group: UI grouping label.
        mode: Whether the snippet replaces the editor or appends to it.
        code: Python/build123d code to insert.
    """
    key: str
    label: str
    group: str
    mode: SnippetMode
    code: str


HEADER = "from build123d import *\n\n"


SNIPPETS: tuple[CodeSnippet, ...] = (
    CodeSnippet(
        key="box",
        label="Box",
        group="Primitives",
        mode="replace",
        code=HEADER + "# Box\npart = Box(10, 10, 10)\n",
    ),
    CodeSnippet(
        key="cylinder",
        label="Cylinder",
        group="Primitives",
        mode="replace",
        code=HEADER + "# Cylinder\npart = Cylinder(radius=5, height=10)\n",
    ),
    CodeSnippet(
        key="sphere",
        label="Sphere",
        group="Primitives",
        mode="replace",
        code=HEADER + "# Sphere\npart = Sphere(radius=5)\n",
    ),
    CodeSnippet(
        key="cone",
        label="Cone",
        group="Primitives",
        mode="replace",
        code=HEADER + "# Cone\npart = Cone(bottom_radius=2, top_radius=4, height=10)\n",
    ),
    CodeSnippet(
        key="torus",
        label="Torus",
        group="Primitives",
        mode="replace",
        code=HEADER + "# Torus\npart = Torus(major_radius=10, minor_radius=2)\n",
    ),
    CodeSnippet(
        key="tube",
        label="Tube",
        group="Primitives",
        mode="replace",
        code=(
            HEADER
            + "# Tube\n"
            + "outer = Cylinder(radius=5, height=10)\n"
            + "inner = Cylinder(radius=2, height=10)\n"
            + "part = outer - inner\n"
        ),
    ),
    CodeSnippet(
        key="fillet_all_edges",
        label="Fillet edges",
        group="Modifiers",
        mode="append",
        code="\npart = fillet(part.edges(), radius=1.0)\n",
    ),
    CodeSnippet(
        key="chamfer_all_edges",
        label="Chamfer edges",
        group="Modifiers",
        mode="append",
        code="\npart = chamfer(part.edges(), length=1.0)\n",
    ),
    CodeSnippet(
        key="move_part",
        label="Move / Pos",
        group="Transforms",
        mode="append",
        code="\npart = Pos(5, 0, 0) * part\n",
    ),
)


def list_snippets() -> list[dict[str, str]]:
    """
    Return snippets as JSON-serializable dictionaries.
    """
    return [asdict(s) for s in SNIPPETS]


def get_snippet(key: str) -> CodeSnippet | None:
    """
    Look up a snippet by key.
    """
    for s in SNIPPETS:
        if s.key == key:
            return s
    return None