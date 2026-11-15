"""The implemented routes and ``openapi.yaml`` must describe the same API."""
from pathlib import Path

import yaml
from fastapi.routing import APIRoute

from app.main import app

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _implemented() -> set[tuple[str, str]]:
    return {
        (route.path, method.lower())
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method.lower() in HTTP_METHODS
    }


def _documented() -> set[tuple[str, str]]:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return {
        (path, method)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }


def test_every_route_is_documented_and_every_documented_route_exists():
    implemented, documented = _implemented(), _documented()

    undocumented = sorted(implemented - documented)
    unimplemented = sorted(documented - implemented)

    assert not undocumented, f"Routes missing from openapi.yaml: {undocumented}"
    assert not unimplemented, f"openapi.yaml operations with no route: {unimplemented}"


# ── Response shapes ──────────────────────────────────────────────────────────
# The frontend's types are generated from openapi.yaml, so a response the spec
# describes wrongly becomes a wrong type on every screen that reads it.


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _name(ref: str) -> str:
    return ref.rsplit("/", 1)[1]


def _spec_parts(node, schemas, seen=None) -> list[tuple[str, dict]]:
    """The object schemas a spec node is made of, each with the name it sits under."""
    seen = set() if seen is None else seen
    if not isinstance(node, dict) or id(node) in seen:
        return []
    seen.add(id(node))
    if "$ref" in node:
        name = _name(node["$ref"])
        return [(name, part) for _, part in _spec_parts(schemas[name], schemas, seen)]
    parts = [("", node)] if "properties" in node else []
    for key in ("allOf", "anyOf", "oneOf"):
        for item in node.get(key, []):
            parts += _spec_parts(item, schemas, seen)
    return parts


def _model(node, schemas) -> dict:
    """The backend's schema for a node, through references and a null alternative."""
    for _ in range(10):
        if not isinstance(node, dict):
            return {}
        if "$ref" in node:
            node = schemas[_name(node["$ref"])]
            continue
        choices = next((node[k] for k in ("anyOf", "allOf", "oneOf") if k in node), None)
        if choices is None:
            return node
        real = [c for c in choices if c.get("type") != "null"]
        if len(real) != 1:
            return {}
        node = real[0]
    return node


def _request_schemas(spec) -> set[str]:
    """Named schemas a request body uses: there a field with a default is optional."""
    schemas, found = spec["components"]["schemas"], set()

    def reach(node):
        if isinstance(node, dict):
            if "$ref" in node and _name(node["$ref"]) in schemas:
                name = _name(node["$ref"])
                if name not in found:
                    found.add(name)
                    reach(schemas[name])
            for value in node.values():
                reach(value)
        elif isinstance(node, list):
            for value in node:
                reach(value)

    for operations in spec["paths"].values():
        for method, operation in operations.items():
            if method in HTTP_METHODS:
                reach(operation.get("requestBody"))
    return found


def _response_problems() -> list[str]:
    spec, built = _spec(), app.openapi()
    schemas, models = spec["components"]["schemas"], built["components"]["schemas"]
    requests = _request_schemas(spec)
    problems, visited = set(), set()

    def walk(where, node, model):
        model = _model(model, models)
        if not isinstance(node, dict) or (id(node), id(model)) in visited:
            return
        visited.add((id(node), id(model)))
        if "$ref" in node:
            return walk(_name(node["$ref"]), schemas[_name(node["$ref"])], model)
        if "items" in node and "items" in model:
            walk(where, node["items"], model["items"])
        if isinstance(node.get("additionalProperties"), dict) and isinstance(
            model.get("additionalProperties"), dict
        ):
            walk(where, node["additionalProperties"], model["additionalProperties"])
        fields = model.get("properties")
        parts = _spec_parts(node, schemas)
        if fields is None or not parts:
            return
        described = {name for _, part in parts for name in part["properties"]}
        for name in sorted(set(fields) - described):
            problems.add(f"{where}: the backend sends '{name}', openapi.yaml leaves it out")
        for part_name, part in parts:
            at = part_name or where
            for name, child in part["properties"].items():
                if name not in fields:
                    problems.add(f"{at}: openapi.yaml has '{name}', the backend never sends it")
                    continue
                if name not in part.get("required", []) and at not in requests:
                    problems.add(f"{at}: '{name}' is always sent, so list it under required")
                walk(f"{at}.{name}", child, fields[name])

    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            answers = built["paths"].get(path, {}).get(method, {}).get("responses", {})
            for code, response in operation.get("responses", {}).items():
                if not str(code).startswith("2"):
                    continue
                ours = response.get("content", {}).get("application/json", {}).get("schema")
                theirs = answers.get(str(code), {}).get("content", {})
                theirs = theirs.get("application/json", {}).get("schema")
                if ours and theirs:
                    walk(f"{method.upper()} {path}", ours, theirs)
    return sorted(problems)


def test_documented_responses_match_the_response_models():
    """A response model always sends every field, so the spec lists each as required.

    A route that returns a plain dictionary has no model to compare with and is
    not checked here.
    """
    problems = _response_problems()
    assert not problems, "openapi.yaml and the response models differ:\n" + "\n".join(problems)


def test_every_schema_in_the_spec_is_used():
    spec = _spec()
    schemas, used = spec["components"]["schemas"], set()

    def reach(node):
        if isinstance(node, dict):
            if "$ref" in node and _name(node["$ref"]) in schemas:
                name = _name(node["$ref"])
                if name not in used:
                    used.add(name)
                    reach(schemas[name])
            for value in node.values():
                reach(value)
        elif isinstance(node, list):
            for value in node:
                reach(value)

    reach(spec["paths"])
    assert not sorted(set(schemas) - used), "Schemas no route uses: remove them"
