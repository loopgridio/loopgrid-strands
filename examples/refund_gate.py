from __future__ import annotations

import json
import os

from strands import Agent, tool
from loopgrid_strands import LoopGridPlugin
from scripted_model import ScriptedRefundModel


@tool
def sandbox_refund(amount: float, currency: str) -> dict:
    """Execute a deterministic sandbox refund with no real money movement.

    Args:
        amount: Refund amount in the requested currency.
        currency: ISO currency code.
    """
    return {
        "status": "succeeded",
        "sandbox": True,
        "real_money_moved": False,
        "external_reference": "strands_demo_refund_001",
        "amount": amount,
        "currency": currency,
    }


def main() -> None:
    plugin = LoopGridPlugin(
        base_url=os.getenv("LOOPGRID_BASE_URL", "http://127.0.0.1:8000"),
        api_key=os.getenv("LOOPGRID_API_KEY"),
        workspace_id=os.getenv("LOOPGRID_WORKSPACE_ID", "default"),
        authority={
            "acting_for": "LoopGrid Strands Demo Store",
            "delegated_by": "loopgrid-strands-example-application",
            "scope": ["refund:create"],
            "limit_usd": 100,
            "environment": "sandbox",
        },
        policy={
            "policy_id": "strands-refund-policy",
            "version": "1",
            "decision": "auto_allowed",
            "reason": "Synthetic duplicate charge is within delegated sandbox threshold.",
            "rule": {"max_refund_usd": 100, "environment": "sandbox"},
            "observed": {"amount": 25, "currency": "USD"},
        },
        proposed_action={
            "type": "refund",
            "tool": "sandbox_refund",
            "amount": 25,
            "currency": "USD",
            "sandbox": True,
            "action_executed_by_loopgrid": False,
        },
        context={"example": "duplicate-charge-refund"},
        capture_content=False,
    )

    agent = Agent(
        model=ScriptedRefundModel(),
        tools=[sandbox_refund],
        plugins=[plugin],
        name="refund-support-agent",
        callback_handler=None,
    )
    run_id = "strands-refund-demo-001"
    result = agent(
        "The customer was charged twice. Execute the authorized $25 sandbox refund.",
        invocation_state={"loopgrid": {"run_id": run_id}},
    )

    # Business outcome is explicit. Agent completion alone is not treated as proof that an
    # external action succeeded.
    plugin.observe_outcome(
        run_id,
        {
            "status": "succeeded",
            "verified_against": "sandbox_refund",
            "external_reference": "strands_demo_refund_001",
            "sandbox": True,
            "real_money_moved": False,
            "amount": 25,
            "currency": "USD",
        },
        observer_id="loopgrid-strands-demo-observer",
    )

    detail = plugin.get_decision(run_id)
    verification = detail["verification"]
    coverage = detail["coverage"]
    lifecycle = detail["summary"]["lifecycle"]

    print("\nSTRANDS RESULT")
    print(str(result))
    print("\nLOOPGRID DECISION")
    print(detail["summary"]["decision_id"])
    print("\nLIFECYCLE")
    print(json.dumps(lifecycle, indent=2))
    print("\nCOVERAGE")
    print(json.dumps(coverage, indent=2))
    print("\nVERIFY")
    print(json.dumps(verification, indent=2))
    print(
        f"\nRESULT: Strands -> LoopGrid -> {detail['summary']['decision_id']} -> "
        f"verified={verification['valid']} | lifecycle={lifecycle['state']} | coverage={coverage['score']}%"
    )
    print("Sandbox only: real_money_moved=false. LoopGrid did not execute the refund.")


if __name__ == "__main__":
    main()
