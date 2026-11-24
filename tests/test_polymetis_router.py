"""Polymetis behind polytropos-router. For each local model, the router calls the hooks in
``polytropos_router_hooks.local_request`` with the request and a slot of ``upstream``, ``model``, ``window`` and
``fits``, and the first hook that returns a request wins (polytropos's docs/reference.md, "Request hooks for local
models"). These tests play the router's part."""

import sys
import types

import pytest
from polymetis_data import INDEX, TOOLS

import polymetis
from polymetis import hooks, log
from polymetis.config import Settings


@pytest.fixture
def linked(tmp_path, monkeypatch):
    """Polymetis registered with the router's hook point, as Hermes would load it."""
    monkeypatch.setitem(sys.modules, "polytropos_router_hooks", types.ModuleType("polytropos_router_hooks"))
    values = {"apply": ["local_tools"], "min_score": 1.0, "local_tools": ["terminal"]}
    monkeypatch.setattr(hooks, "_get_config", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(hooks, "_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(hooks, "_settings", Settings())
    hooks.STORE.clear()
    polymetis._router_hooks()["polymetis"] = hooks.shape_local
    yield values
    hooks.STORE.clear()


def hermes_turn(text, messages):
    hooks.on_pre_llm_call(session_id="s1", turn_id="t", user_message=text, platform="cli", model="router")
    hooks.on_pre_api_request(session_id="s1", platform="cli", model="router", provider="polytropos-router",
                             system_prompt=INDEX, request_messages=messages, request={"body": {"tools": TOOLS}})


def route(request, window_fits=lambda r: True):
    """What the router does for one local model: the first hook that returns a request wins."""
    slot = {"upstream": "local", "model": "small", "window": 8192, "fits": window_fits}
    for hook in sys.modules["polytropos_router_hooks"].local_request.values():
        out = hook(request, slot)
        if out is not None:
            return out
    return None


def test_the_local_model_gets_the_session_variant(linked, tmp_path):
    text = "Please merge my pull request"
    messages = [{"role": "system", "content": INDEX}, {"role": "user", "content": text}]
    hermes_turn(text, messages)
    out = route({"model": "auto", "messages": messages, "tools": TOOLS})
    assert out["variant"] == "lean"
    assert [t["function"]["name"] for t in out["request"]["tools"]] == ["terminal", "skill_view"]
    system = out["request"]["messages"][0]["content"]
    assert "github-pr-workflow" in system and "ascii-art" not in system
    hooks.on_session_end(session_id="s1", completed=True)
    assert log.read(tmp_path / "data" / log.NAME)[0]["local"] == "lean"


def test_a_variant_that_does_not_fit_steps_down(linked):
    text = "Please merge my pull request"
    messages = [{"role": "system", "content": INDEX}, {"role": "user", "content": text}]
    hermes_turn(text, messages)
    out = route({"model": "auto", "messages": messages, "tools": TOOLS}, window_fits=lambda r: not r.get("tools"))
    assert out["variant"] == "bare" and not out["request"].get("tools")


def test_without_apply_the_router_sends_the_request_unchanged(linked):
    linked["apply"] = []
    text = "Please merge my pull request"
    messages = [{"role": "system", "content": INDEX}, {"role": "user", "content": text}]
    hermes_turn(text, messages)
    assert route({"model": "auto", "messages": messages, "tools": TOOLS}) is None
