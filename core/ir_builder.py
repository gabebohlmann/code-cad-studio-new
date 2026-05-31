# core/ir_builder.py

from __future__ import annotations

from typing import Any

from core.ir import IRDocument, IRFeature, IRObject


class IRBuilder:
    def __init__(self, source_mode: str = "unknown"):
        self.doc = IRDocument(source_mode=source_mode)
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"feat_{self._counter:03d}"

    def add_variable(self, name: str, value: Any) -> None:
        self.doc.variables[name] = value

    def add_object(self, name: str, root: str | None, kind: str = "part") -> None:
        self.doc.objects.append(
            IRObject(
                id=name,
                name=name,
                kind=kind,
                root=root,
            )
        )

    def add_primitive(
        self,
        type_name: str,
        name: str,
        params: dict[str, Any],
        placement: dict[str, Any] | None = None,
    ) -> str:
        fid = self.next_id()
        self.doc.features.append(
            IRFeature(
                id=fid,
                type=f"primitive.{type_name}",
                name=name,
                params=params,
                placement=placement,
            )
        )
        return fid

    def add_boolean(self, op: str, name: str, base: str, tool: str) -> str:
        fid = self.next_id()
        op_type = {
            "+": "boolean.fuse",
            "-": "boolean.cut",
            "&": "boolean.common",
        }[op]

        self.doc.features.append(
            IRFeature(
                id=fid,
                type=op_type,
                name=name,
                base=base,
                tool=tool,
            )
        )
        return fid

    def add_modifier(
        self,
        mod_type: str,
        name: str,
        base: str,
        params: dict[str, Any],
        selector: dict[str, Any] | None = None,
    ) -> str:
        fid = self.next_id()

        self.doc.features.append(
            IRFeature(
                id=fid,
                type=f"modifier.{mod_type}",
                name=name,
                base=base,
                params=params,
                selector=selector,
            )
        )
        return fid