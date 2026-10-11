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
