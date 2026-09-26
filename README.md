# LoopGrid × Strands Agents

**Verifiable evidence for consequential Strands agent decisions.**

**Strands runs the agent. LoopGrid preserves the evidence.**

`loopgrid-strands` is a native Strands Agents `Plugin` that records framework lifecycle facts and explicit application evidence into LoopGrid's signed, append-only decision record.

It is intentionally **not another tracing backend**. Keep Strands/OpenTelemetry/your observability stack. LoopGrid adds the evidence semantics needed to prove consequential decisions: delegated authority, application policy, human review, external action evidence, observed business outcome, and cryptographic verification.

## What v0.1.0 records

| Source | LoopGrid evidence |
|---|---|
| Strands invocation start | `decision_created` |
| Successful model call | `model_completed` |
| Explicit application policy | `policy_evaluated` |
| Strands tool about to run | `tool_requested` |
| Successful Strands tool execution | `tool_executed` |
| Failed Strands tool execution | `tool_result` |
| Model failure | `incident_flagged` |
| Native LoopGrid review helper | `human_approved` / `human_rejected` through `/review` |
| Explicit application-observed result | `outcome_observed` |

A completed agent invocation is **not** automatically treated as a successful business outcome.

## Install

```bash
pip install loopgrid-strands
```

Requires Python 3.10+ and Strands Agents 1.57.1+.

## Quickstart

```python
from strands import Agent
from loopgrid_strands import LoopGridPlugin

plugin = LoopGridPlugin(
    base_url="http://127.0.0.1:8000",
    api_key="lg_live_...",
    workspace_id="default",
    authority={
        "acting_for": "Example Store",
        "scope": ["refund:create"],
        "limit_usd": 100,
    },
    policy={
        "policy_id": "refund-policy",
        "version": "1",
        "decision": "auto_allowed",
        "reason": "Within delegated threshold.",
    },
    proposed_action={"tool": "refund.create", "amount": 25, "currency": "USD"},
)

agent = Agent(plugins=[plugin], name="support-agent", tools=[...], model=...)
run_id = "case-123"
result = agent(
    "Handle this duplicate charge.",
    invocation_state={"loopgrid": {"run_id": run_id}},
)

# Only after your application has observed the real external result:
plugin.observe_outcome(
    run_id,
    {"status": "succeeded", "external_reference": "refund_123"},
)
```

Strands invocation state is the per-request configuration channel. It is shared across hooks/tools during one invocation and is not added to model context. In the current Python SDK, `AgentResult.state` is the event-loop/request-state slot rather than a mirror of arbitrary caller `invocation_state`, so keep the LoopGrid `run_id` explicitly as shown above. You may override application evidence per request:

```python
result = agent(
    "Handle this request",
    invocation_state={
        "loopgrid": {
            "run_id": "case-456",
            "authority": {"scope": ["refund:create"], "limit_usd": 50},
            "policy": {
                "policy_id": "refund-policy",
                "version": "7",
                "decision": "auto_allowed",
                "reason": "Within delegated threshold",
            },
            "proposed_action": {"tool": "refund.create", "amount": 25, "currency": "USD"},
            "context": {"policy_bundle": "support-prod-7"},
        }
    },
)
```

## Dynamic policy

LoopGrid does not manufacture a policy decision from a trace. If the policy is determined after a model response, your application or a separate Strands policy/intervention hook can call:

```python
plugin.record_policy(
    run_id,
    {
        "policy_id": "refund-policy",
        "version": "7",
        "decision": "human_approval_required",
        "reason": "Amount exceeds automatic threshold",
    },
)
```

For a human-gated path, submit the real review through LoopGrid's native review endpoint:

```python
plugin.review_run(run_id, "approve", "reviewer@example.com", "Checked account history")
```

Your application/Strands intervention remains responsible for actually blocking or permitting the tool. The LoopGrid plugin records and verifies evidence; it is not the tool executor or policy enforcement engine.

## Privacy

Raw prompts, model messages, tool inputs/results, and exception text are **not stored by default**. The plugin records SHA-256 commitments and structural metadata. Set `capture_content=True` only when your privacy policy allows raw content capture.

`fail_open=False` is the default. For consequential workflows, evidence-write failures are surfaced rather than silently losing the record. `fail_open=True` is available when your application explicitly prefers availability over evidence completeness.

## Deterministic no-cost validation

The repository includes a real Strands `Agent` runtime test and demo using a deterministic custom `Model`. It makes **no AWS/Bedrock/OpenAI/Anthropic/Gemini call** and requires no card or cloud account.

```bash
pip install -e ".[dev]"
python -m pytest -v
```

With LoopGrid Core running locally:

```bash
python examples/refund_gate.py
```

Release gate for the canonical demo:

```text
Strands Agent
→ model_completed
→ application policy_evaluated
→ tool_requested
→ sandbox tool_executed
→ explicit outcome_observed
→ evidence_complete
→ coverage 100%
→ verify valid:true
```

The included refund example is sandbox-only and explicitly records `real_money_moved=false`.

## Neutrality boundary

- **Strands Agents:** runs/orchestrates the agent and tools.
- **Your application:** owns delegated authority, business policy, reviews, and external outcome semantics.
- **LoopGrid:** records signed evidence and verifies the resulting decision lifecycle.

Independent community integration. Not affiliated with or endorsed by Amazon Web Services or the Strands Agents project.

## License

Apache-2.0.
