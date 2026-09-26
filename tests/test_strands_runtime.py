from __future__ import annotations

from strands import Agent, tool

from loopgrid_strands import LoopGridPlugin
from examples.scripted_model import ScriptedRefundModel


class FakeGrid:
    def __init__(self):
        self.calls = []
        self.decision_id = "dec_runtime"

    def record_decision(self, **kwargs):
        self.calls.append(("decision_created", kwargs))
        return {"decision_id": self.decision_id}

    def add_event(self, decision_id, event_type, payload, actor_type="system", actor_id="loopgrid", **kwargs):
        self.calls.append((event_type, payload))
        return {"event_type": event_type}

    def get_decision(self, decision_id):
        return {"summary": {"decision_id": decision_id, "agent": {"id": "runtime-agent"}}}

    def verify_workspace(self):
        return {"valid": True}

    def review(self, decision_id, action, reviewer, reason=""):
        return {"ok": True}


@tool
def sandbox_refund(amount: float, currency: str) -> dict:
    """Return a sandbox-only refund result.

    Args:
        amount: Amount to refund.
        currency: ISO currency code.
    """
    return {"status": "succeeded", "sandbox": True, "real_money_moved": False, "amount": amount, "currency": currency}


def test_actual_strands_agent_plugin_tool_lifecycle():
    grid = FakeGrid()
    plugin = LoopGridPlugin(
        client=grid,
        authority={"scope": ["refund:create"], "environment": "sandbox"},
        policy={"policy_id": "p1", "version": "1", "decision": "auto_allowed", "reason": "test"},
        proposed_action={"tool": "sandbox_refund", "amount": 25, "currency": "USD"},
    )
    agent = Agent(
        model=ScriptedRefundModel(),
        tools=[sandbox_refund],
        plugins=[plugin],
        name="runtime-agent",
        callback_handler=None,
    )
    run_id = "runtime-1"
    result = agent("Run sandbox refund", invocation_state={"loopgrid": {"run_id": run_id}})

    # Strands Python exposes AgentResult.state as the event-loop/request-state slot,
    # not as a mirror of arbitrary caller invocation_state. The LoopGrid run id is
    # caller-owned evidence context, so keep/use it explicitly.
    assert str(result).strip() == "Sandbox refund workflow completed."
    assert plugin.decision_id_for(run_id) == grid.decision_id
    plugin.observe_outcome(run_id, {"status": "succeeded", "sandbox": True, "real_money_moved": False})
    types = [name for name, _ in grid.calls]
    assert types == [
        "decision_created",
        "model_completed",
        "policy_evaluated",
        "tool_requested",
        "tool_executed",
        "model_completed",
        "outcome_observed",
    ]
    snap = plugin.snapshot_for("runtime-1")
    assert snap is not None
    assert snap.model_turns == 2
    assert snap.final_agent_result_sha256
    assert snap.last_tool_result_sha256
