"""Minimal JSON schema check: type, required, enum, properties, items, minimum. Nothing else."""

from __future__ import annotations

from typing import Any, List

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _type_ok(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def validate(value: Any, schema: dict, path: str = "$") -> List[str]:
    """Return a list of error strings. Empty list means valid."""
    errors: List[str] = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, name) for name in names):
            return [f"{path}: expected {'/'.join(names)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if "minimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema["minimum"]:
            errors.append(f"{path}: {value} is below {schema['minimum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            known = set(schema.get("properties", {}))
            for key, item in value.items():
                if key not in known:
                    errors.extend(validate(item, extra, f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    return errors


def check(value: Any, schema: dict, what: str) -> None:
    """Raise ValueError with all errors if the value does not match."""
    errors = validate(value, schema)
    if errors:
        raise ValueError(f"Invalid {what}: " + "; ".join(errors[:5]))
