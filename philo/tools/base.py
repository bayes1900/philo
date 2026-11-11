from abc import ABC, abstractmethod
from typing import Any


class ToolBase(ABC):
    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        pass

    def getSchema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def castParams(self, params: dict[str, Any]) -> dict[str, Any]:
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params
        return self.castObject(params, schema)

    def castObject(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return obj
        props = schema.get("properties", {})
        result = {}
        for key, value in obj.items():
            if key in props:
                result[key] = self.castValue(value, props[key])
            else:
                result[key] = value
        return result

    def castValue(self, val: Any, schema: dict[str, Any]) -> Any:
        targetType = schema.get("type")
        if targetType == "boolean" and isinstance(val, bool):
            return val
        if targetType == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        if targetType in self.TYPE_MAP and targetType not in ("boolean", "integer", "array", "object"):
            expected = self.TYPE_MAP[targetType]
            if isinstance(val, expected):
                return val
        if targetType == "integer" and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return val
        if targetType == "number" and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return val
        if targetType == "string":
            return val if val is None else str(val)
        if targetType == "boolean" and isinstance(val, str):
            valLower = val.lower()
            if valLower in ("true", "1", "yes"):
                return True
            if valLower in ("false", "0", "no"):
                return False
            return val
        if targetType == "array" and isinstance(val, list):
            itemSchema = schema.get("items")
            return [self.castValue(item, itemSchema) for item in val] if itemSchema else val
        if targetType == "object" and isinstance(val, dict):
            return self.castObject(val, schema)
        return val

    def validateParams(self, params: dict[str, Any]) -> list[str]:
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self.validate(params, {**schema, "type": "object"}, "")

    def validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        t, label = schema.get("type"), path or "parameter"
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]
        if t == "number" and (not isinstance(val, self.TYPE_MAP[t]) or isinstance(val, bool)):
            return [f"{label} should be number"]
        if t in self.TYPE_MAP and t not in ("integer", "number") and not isinstance(val, self.TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors = []
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        if t == "object":
            props = schema.get("properties", {})
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            for k, v in val.items():
                if k in props:
                    errors.extend(self.validate(v, props[k], path + "." + k if path else k))
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(
                    self.validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]")
                )
        return errors
