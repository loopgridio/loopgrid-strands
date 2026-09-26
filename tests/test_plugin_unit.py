from __future__ import annotations

from types import SimpleNamespace

import pytest

from loopgrid_strands import LoopGridPlugin


class FakeGrid:
    def __init__(self):
        self.calls = []
        self.n = 0

    def record_decision(self, **kwargs):
        self.n += 1
        self.calls.append(("decision_created", kwargs))
        return {"decision_id": f"dec_{self.n}"}

    def add_event(self, decision_id, event_type, payload, actor_type="system", actor_id="loopgrid", **kwargs):
        self.calls.append((event_type, {"decision_id": decision_id, "payload": payload, "actor_type": actor_type, "actor_id": actor_id, **kwargs}))
        return {"event_type": event_type}

    def get_decision(self, decision_id):
        return {"summary": {"decision_id": decision_id, "agent": {"id": "agent-1"}}}

    def verify_workspace(self):
        return {"valid": True}

    def review(self, decision_id, action, reviewer, reason=""):
        self.calls.append(("review", {"decision_id": decision_id, "action": action, "reviewer": reviewer, "reason": reason}))
        return {"ok": True}


class FakeModel:
    def get_config(self):
        return {"provider": "test-provider", "model_id": "test-model"}


class FakeAgent:
    agent_id = "agent-1"
    name = "Test Strands Agent"
    model = FakeModel()


def event(**kwargs):
    return SimpleNamespace(agent=FakeAgent(), **kwargs)


def make_plugin(grid=None, **kwargs):
    return LoopGridPlugin(
        client=grid or FakeGrid(),
        authority={"scope": ["refund:create"]},
        policy={"policy_id": "p1", "version": "1", "decision": "auto_allowed", "reason": "test"},
        proposed_action={"tool": "sandbox_refund"},
        **kwargs,
    )


def start(plugin, state=None):
    state = state or {"loopgrid": {"run_id": "run-1"}}
    plugin.before_invocation(event(invocation_state=state, messages=[{"role": "user", "content": [{"text": "hello"}]}], cancel=False))
    return state


def model_ok(plugin, state, text="ok"):
    stop = SimpleNamespace(stop_reason="end_turn", message={"role": "assistant", "content": [{"text": text}]})
    plugin.after_model(event(invocation_state=state, stop_response=stop, exception=None, retry=False))



def test_plugin_initializes_native_strands_hook_registry():
    plugin = make_plugin()
    # Regression guard: Strands Agent reads plugin.hooks during registration.
    # Plugin.__init__ must therefore have discovered our @hook methods.
    assert len(plugin.hooks) >= 5


def test_native_lifecycle_mapping_and_explicit_outcome():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    model_ok(plugin, state)
    tool_use = {"name": "sandbox_refund", "toolUseId": "t1", "input": {"amount": 25}}
    plugin.before_tool(event(invocation_state=state, tool_use=tool_use, selected_tool=None, cancel_tool=False))
    plugin.after_tool(event(invocation_state=state, tool_use=tool_use, selected_tool=None, result={"status": "success"}, cancel_message=None, retry=False))
    plugin.after_invocation(event(invocation_state=state, result={"message": "done"}, resume=None))
    plugin.observe_outcome("run-1", {"status": "succeeded", "sandbox": True})

    types = [name for name, _ in grid.calls]
    assert types == [
        "decision_created",
        "model_completed",
        "policy_evaluated",
        "tool_requested",
        "tool_executed",
        "outcome_observed",
    ]
    assert plugin.snapshot_for("run-1").final_agent_result_sha256


def test_invocation_state_overrides_defaults():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = {"loopgrid": {"run_id": "run-2", "authority": {"limit_usd": 50}, "context": {"case": "x"}}}
    start(plugin, state)
    decision = grid.calls[0][1]
    assert decision["authority"]["scope"] == ["refund:create"]
    assert decision["authority"]["limit_usd"] == 50
    assert decision["context"]["application"]["case"] == "x"
    assert state["loopgrid"]["decision_id"] == "dec_1"


def test_raw_content_is_not_stored_by_default():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    decision = grid.calls[0][1]
    assert "messages" not in decision["input"]
    model_ok(plugin, state, "secret response")
    model_payload = next(v["payload"] for n, v in grid.calls if n == "model_completed")
    assert "message" not in model_payload
    assert model_payload["message_sha256"]


def test_capture_content_opt_in():
    grid = FakeGrid()
    plugin = make_plugin(grid, capture_content=True)
    state = start(plugin)
    assert "messages" in grid.calls[0][1]["input"]
    model_ok(plugin, state, "visible")
    model_payload = next(v["payload"] for n, v in grid.calls if n == "model_completed")
    assert "message" in model_payload


def test_failed_tool_is_tool_result_not_executed():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    model_ok(plugin, state)
    tool_use = {"name": "sandbox_refund", "toolUseId": "t1", "input": {}}
    plugin.before_tool(event(invocation_state=state, tool_use=tool_use, selected_tool=None, cancel_tool=False))
    plugin.after_tool(event(invocation_state=state, tool_use=tool_use, selected_tool=None, result=RuntimeError("boom"), cancel_message=None, retry=False))
    assert [n for n, _ in grid.calls][-1] == "tool_result"
    payload = grid.calls[-1][1]["payload"]
    assert payload["status"] == "failed"
    assert payload["error_sha256"]


def test_model_failure_records_incident_without_raw_error():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    plugin.after_model(event(invocation_state=state, stop_response=None, exception=RuntimeError("private failure"), retry=False))
    assert grid.calls[-1][0] == "incident_flagged"
    payload = grid.calls[-1][1]["payload"]
    assert "private failure" not in str(payload)
    assert payload["error_type"] == "RuntimeError"


def test_policy_is_explicit_and_only_once():
    grid = FakeGrid()
    plugin = LoopGridPlugin(client=grid, authority={"scope": ["x"]})
    state = start(plugin)
    model_ok(plugin, state)
    assert "policy_evaluated" not in [n for n, _ in grid.calls]
    plugin.record_policy("run-1", {"policy_id": "later", "version": "1", "decision": "auto_allowed"})
    with pytest.raises(RuntimeError):
        plugin.record_policy("run-1", {"policy_id": "later", "version": "1", "decision": "auto_allowed"})


def test_review_uses_native_review_endpoint():
    grid = FakeGrid()
    plugin = LoopGridPlugin(
        client=grid,
        authority={"scope": ["x"]},
        policy={"policy_id": "p", "version": "1", "decision": "human_approval_required"},
    )
    state = start(plugin)
    model_ok(plugin, state)
    plugin.review_run("run-1", "approve", "reviewer@example.com", "approved")
    assert grid.calls[-1][0] == "review"
    assert grid.calls[-1][1]["action"] == "approve"


def test_invalid_policy_decision_rejected():
    grid = FakeGrid()
    plugin = LoopGridPlugin(client=grid, authority={"scope": ["x"]})
    start(plugin)
    with pytest.raises(ValueError):
        plugin.record_policy("run-1", {"policy_id": "p", "version": "1", "decision": "made_up"})


def test_fail_open_does_not_raise_transport_errors():
    class BrokenGrid(FakeGrid):
        def record_decision(self, **kwargs):
            raise RuntimeError("down")
    plugin = LoopGridPlugin(client=BrokenGrid(), fail_open=True)
    state = {"loopgrid": {"run_id": "run-fail-open"}}
    plugin.before_invocation(event(invocation_state=state, messages=[], cancel=False))
    assert "decision_id" not in state["loopgrid"]


def test_cancelled_tool_is_not_recorded_as_executed():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    model_ok(plugin, state)
    tool_use = {"name": "sandbox_refund", "toolUseId": "cancel-1", "input": {}}
    plugin.before_tool(event(invocation_state=state, tool_use=tool_use, selected_tool=None, cancel_tool=False))
    plugin.after_tool(event(
        invocation_state=state,
        tool_use=tool_use,
        selected_tool=None,
        result={"toolUseId": "cancel-1", "status": "error", "content": [{"text": "cancelled"}]},
        cancel_message="approval required",
        retry=False,
    ))
    assert grid.calls[-1][0] == "tool_result"
    assert grid.calls[-1][1]["payload"]["status"] == "cancelled"


def test_model_marked_for_retry_does_not_commit_policy_yet():
    grid = FakeGrid()
    plugin = make_plugin(grid)
    state = start(plugin)
    stop = SimpleNamespace(stop_reason="end_turn", message={"role": "assistant", "content": [{"text": "discard me"}]})
    plugin.after_model(event(invocation_state=state, stop_response=stop, exception=None, retry=True))
    assert [n for n, _ in grid.calls] == ["decision_created", "model_completed"]
    plugin.after_model(event(invocation_state=state, stop_response=stop, exception=None, retry=False))
    assert [n for n, _ in grid.calls][-2:] == ["model_completed", "policy_evaluated"]
