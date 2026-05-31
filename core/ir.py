# core/ir.py

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class IRFeature:
    id: str
    type: str
    name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    placement: dict[str, Any] | None = None

    # Feature graph links
    base: str | None = None
    tool: str | None = None

    # For fillet/chamfer later
    selector: dict[str, Any] | None = None


@dataclass
class IRObject:
    id: str
    name: str
    kind: str = "part"
    root: str | None = None


@dataclass
class IRDocument:
    schema: str = "codecad.ir.v0"
    units: str = "mm"
    source_mode: str = "unknown"
    variables: dict[str, Any] = field(default_factory=dict)
    objects: list[IRObject] = field(default_factory=list)
    features: list[IRFeature] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)