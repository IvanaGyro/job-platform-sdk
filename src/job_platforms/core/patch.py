"""JSON Pointer / JSON Patch support for local resume edit plans.

All operations work on deep copies. No website write is performed here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal
import re


@dataclass(frozen=True)
class JsonPatchOperation:
    op: Literal["add", "replace", "remove", "test"]
    path: str
    value: Any = None

    @classmethod
    def from_dict(cls, data: dict) -> "JsonPatchOperation":
        if not isinstance(data, dict) or set(data) - {"op", "path", "value"}:
            raise ValueError("Unexpected JSON Patch fields")
        if data.get("op") not in {"add", "replace", "remove", "test"}:
            raise ValueError("Unsupported JSON Patch operation")
        if not isinstance(data.get("path"), str):
            raise ValueError("JSON Pointer must be a string")
        if data["op"] in ("add", "replace", "test") and "value" not in data:
            raise ValueError("JSON Patch value missing")
        return cls(data["op"], data["path"], data.get("value"))


@dataclass
class EditPlan:
    resume_id: str
    base_timestamp: str | int | None
    operations: list[JsonPatchOperation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "resume_id": self.resume_id,
            "base_timestamp": self.base_timestamp,
            "operations": [
                {"op": op.op, "path": op.path,
                 **({"value": op.value} if op.op != "remove" else {})}
                for op in self.operations
            ],
        }


def _tokens(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'")
    segments = path[1:].split("/")
    if any(re.search(r"~(?![01])", item) for item in segments):
        raise ValueError("Invalid JSON Pointer escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in segments]


def _index(token: str, length: int, *, for_add: bool = False) -> int:
    if token == "-" and for_add:
        return length
    if not token.isdigit() or len(token) > 1 and token[0] == "0":
        raise ValueError("Invalid JSON array index")
    index = int(token)
    if index >= length + int(for_add):
        raise IndexError("JSON Patch array index out of bounds")
    return index


def _lookup(value: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list):
            value = value[_index(part, len(value))]
        else:
            raise TypeError("Cannot address scalar descendants")
    return value


def apply_json_patch(document: Any, operations: list[JsonPatchOperation]) -> Any:
    """Create a modified copy; never mutate the provided document."""
    value = deepcopy(document)
    for operation in operations:
        parts = _tokens(operation.path)
        if not parts:
            raise ValueError("Changing the entire root document is prohibited")
        if operation.op == "test":
            if _lookup(value, parts) != operation.value:
                raise ValueError("JSON Patch test failed")
            continue
        parent = _lookup(value, parts[:-1])
        key = parts[-1]
        if isinstance(parent, list):
            index = _index(key, len(parent), for_add=operation.op == "add")
            if operation.op == "add":
                parent.insert(index, deepcopy(operation.value))
            elif operation.op == "replace":
                parent[index] = deepcopy(operation.value)
            else:
                parent.pop(index)
        elif isinstance(parent, dict):
            if operation.op == "add":
                parent[key] = deepcopy(operation.value)
            elif operation.op == "replace":
                if key not in parent:
                    raise KeyError("Cannot replace a nonexistent field")
                parent[key] = deepcopy(operation.value)
            else:
                del parent[key]
        else:
            raise TypeError("JSON Patch target must be a container")
    return value


def describe_schema(document: Any, *, max_depth: int = 24) -> Any:
    """Report nested types, keys and counts without exposing personal values."""
    def describe(value: Any, depth: int) -> Any:
        if depth < 0:
            return {"type": "nested"}
        if isinstance(value, dict):
            return {"type": "object", "properties": {
                str(k): describe(child, depth - 1) for k, child in value.items()
            }}
        if isinstance(value, list):
            return {"type": "array", "count": len(value),
                    "items": describe(value[0], depth - 1) if value
                    else {"type": "unknown"}}
        return {"type": "null" if value is None else type(value).__name__}
    return describe(document, max_depth)
