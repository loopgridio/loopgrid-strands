from __future__ import annotations

from typing import Any, AsyncIterable

from strands.models import Model


class ScriptedRefundModel(Model):
    """Deterministic no-network Strands model used only by the example/test."""

    def __init__(self) -> None:
        self.config = {"provider": "loopgrid-scripted", "model_id": "strands-scripted-refund-v1"}
        self.turn = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    async def stream(
        self,
        messages,
        tool_specs=None,
        system_prompt=None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, Any]]:
        self.turn += 1
        if self.turn == 1:
            yield {"messageStart": {"role": "assistant"}}
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "refund-call-1", "name": "sandbox_refund"}}
                }
            }
            yield {
                "contentBlockDelta": {
                    "delta": {"toolUse": {"input": '{"amount":25,"currency":"USD"}'}}
                }
            }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
            yield {"metadata": {"usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20}, "metrics": {"latencyMs": 1}}}
        else:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Sandbox refund workflow completed."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 8, "outputTokens": 5, "totalTokens": 13}, "metrics": {"latencyMs": 1}}}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs: Any):
        raise NotImplementedError("ScriptedRefundModel is only for the normal agent-loop demo")
        yield {}  # pragma: no cover
