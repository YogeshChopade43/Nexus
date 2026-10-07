from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workflows import inputs

NUM = [{"name": "n", "type": "number", "required": True}]
FLAG = [{"name": "flag", "type": "boolean", "required": True}]


def test_number_is_coerced():
    assert inputs.coerce(NUM, {"n": "3"}) == {"n": 3}


def test_number_rejects_text():
    with pytest.raises(ValueError, match="n"):
        inputs.coerce(NUM, {"n": "abc"})


@pytest.mark.parametrize("raw,expected", [("false", False), ("true", True), (True, True), (False, False)])
def test_boolean_strings_coerce(raw, expected):
    assert inputs.coerce(FLAG, {"flag": raw}) == {"flag": expected}


def test_boolean_rejects_unknown_text():
    with pytest.raises(ValueError):
        inputs.coerce(FLAG, {"flag": "maybe"})


def test_missing_required_is_named():
    with pytest.raises(ValueError, match="who"):
        inputs.coerce([{"name": "who", "type": "text", "required": True}], {})


def test_optional_default_fills_in():
    assert inputs.coerce([{"name": "x", "type": "text", "required": False, "default": "d"}], {}) == {"x": "d"}


@pytest.mark.parametrize("defs", [
    [{"name": "1x", "type": "text"}],
    [{"name": "a", "type": "text"}, {"name": "a", "type": "number"}],
    [{"name": f"i{n}", "type": "text"} for n in range(21)],
    [{"name": "a", "type": "date"}],
])
def test_bad_definitions_rejected(defs):
    with pytest.raises(ValueError):
        inputs.validate_definitions(defs)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_manual_inputs_reach_steps(client):
    trigger = {"trigger_type": "manual", "inputs": [{"name": "who", "type": "text", "required": True}]}
    r = client.post("/api/workflows", json={
        "name": "greet", "isActive": True,
        "nodes": [{"id": "t", "type": "trigger", "config": trigger},
                  {"id": "x", "type": "transform", "config": {"template": "hi {{ trigger.inputs.who }}"}}],
        "edges": [{"source": "t", "target": "x"}],
    })
    assert r.status_code == 200, r.text
    wf = r.json()
    assert wf["trigger_config"]["inputs"][0]["name"] == "who"

    run = client.post(f"/api/workflows/{wf['id']}/run", json={"input_data": {"who": "ana"}}).json()
    assert run["status"] == "completed", run
    assert run["events"][0]["output"]["value"] == "hi ana"
    listed = {w["id"]: w for w in client.get("/api/workflows").json()}
    assert listed[wf["id"]]["last_status"] == "completed"

    assert client.post(f"/api/workflows/{wf['id']}/run", json={}).status_code == 400

    bad = {**trigger, "inputs": [{"name": "bad name", "type": "text"}]}
    r = client.patch(f"/api/workflows/{wf['id']}", json={"nodes": [{"id": "t", "type": "trigger", "config": bad}], "edges": []})
    assert r.status_code == 400
