"""Marketplace: install recipes (form fields + server config) from MCP Registry entries. Hosted servers only."""
from __future__ import annotations

import pytest

from app.mcp.recipes import fill, plan

HOSTED = {"type": "streamable-http", "url": "https://x/mcp",
          "headers": [{"name": "Authorization", "value": "Bearer {api_key}", "isRequired": True, "isSecret": True,
                       "description": "Key"}]}
NPM = {"registryType": "npm", "identifier": "@a/srv", "version": "1.2.0", "transport": {"type": "stdio"}}


def test_hosted_with_secret_header():
    recipe = plan({"name": "io.x/h", "remotes": [HOSTED]})
    assert recipe["kind"] == "hosted"
    assert recipe["fields"] == [{"key": "api_key", "label": "api_key", "description": "Key", "required": True,
                                 "secret": True, "default": ""}]
    server = fill(recipe, {"api_key": "k1"})
    assert server == {"transport": "http", "url": "https://x/mcp", "headers": {"Authorization": "Bearer k1"}}
    with pytest.raises(ValueError, match="api_key is required"):
        fill(recipe, {})


def test_url_placeholders_and_optional_headers():
    recipe = plan({"name": "io.x/u", "remotes": [{"type": "streamable-http", "url": "https://{region}.x.io/mcp",
                                                  "variables": {"region": {"default": "eu"}},
                                                  "headers": [{"name": "X-Team", "description": "Optional team"}]}]})
    assert fill(recipe, {}) == {"transport": "http", "url": "https://eu.x.io/mcp", "headers": {}}
    assert fill(recipe, {"region": "us", "X-Team": "t1"})["headers"] == {"X-Team": "t1"}


def test_local_servers_are_not_installable():
    """Nexus only connects to hosted servers: packages it would have to run on this computer are left out."""
    assert plan({"name": "a", "packages": [NPM]}) is None
    assert plan({"name": "b", "packages": [{**NPM, "registryType": "pypi"}]}) is None
    assert plan({"name": "c", "remotes": [HOSTED], "packages": [NPM]})["kind"] == "hosted"


def test_not_installable():
    assert plan({"name": "a", "packages": [{"registryType": "oci", "identifier": "img"}]}) is None
    assert plan({"name": "b", "remotes": [{"type": "sse", "url": "https://x/sse"}]}) is None
    assert plan({"name": "c"}) is None
