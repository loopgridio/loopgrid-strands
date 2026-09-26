from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from loopgrid import LoopGrid
from strands.hooks import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
)
from strands.plugins import Plugin, hook

_JSON_SCALARS = (str, int, float, bool, type(None))
_ALLOWED_POLICY_DECISIONS = {"auto_allowed", "human_approval_required", "blocked", "block"}


def _jsonable(value: Any) -> Any:
    """Best-effort JSON-safe projection for hashing/evidence payloads."""
    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    if dataclasses.is_dataclass(value):
        try:
            return _jsonable(dataclasses.asdict(value))
        except Exception:
            pass
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except TypeError:
            return _jsonable(model_dump())
        except Exception:
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            data = {k: v for k, v in vars(value).items() if not str(k).startswith("_")}
            if data:
                return _jsonable(data)
        except Exception:
            pass
    return {"type": type(value).__name__, "repr": repr(value)[:500]}


def _sha256(value: Any) -> str:
    raw = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _strands_version() -> str:
    try:
        return importlib.metadata.version("strands-agents")
    except Exception:
        return "unknown"


def _model_provenance(agent: Any) -> dict[str, Any]:
    model = getattr(agent, "model", None)
    config: dict[str, Any] = {}
    get_config = getattr(model, "get_config", None)
    if callable(get_config):
        try:
            raw = get_config() or {}
            if isinstance(raw, Mapping):
                config = dict(raw)
        except Exception:
            config = {}

    name = (
        config.get("model_id")
        or config.get("model")
        or config.get("model_name")
        or getattr(model, "model_id", None)
        or getattr(model, "model_name", None)
        or type(model).__name__
    )
    provider = config.get("provider") or config.get("provider_name")
    if not provider:
        module = type(model).__module__ if model is not None else ""
        marker = "strands.models."
        if marker in module:
            provider = module.split(marker, 1)[1].split(".", 1)[0]
        elif module.startswith("strands."):
            provider = "strands"
        else:
            provider = "custom"
    return {"provider": str(provider), "name": str(name)}


def _event_error_payload(exc: BaseException, *, framework: str, run_id: str, stage: str) -> dict[str, Any]:
    return {
        "framework": framework,
        "run_id": run_id,
        "stage": stage,
        "error_type": type(exc).__name__,
        "error_sha256": _sha256(str(exc)),
    }


def _policy_payload(policy: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(_jsonable(dict(policy)))
    decision = payload.get("decision")
    if decision not in _ALLOWED_POLICY_DECISIONS:
        raise ValueError(
            "LoopGrid policy evidence requires decision to be one of: "
            "auto_allowed, human_approval_required, blocked"
        )
    if not (payload.get("policy_id") or payload.get("version")):
        raise ValueError("LoopGrid policy evidence should include policy_id or version")
    return payload


@dataclass
class _RunState:
    decision_id: str
    run_id: str
    agent_id: str
    model: dict[str, Any]
    policy: dict[str, Any] = field(default_factory=dict)
    policy_recorded: bool = False
    model_turn: int = 0
    tool_attempt_by_id: dict[str, int] = field(default_factory=dict)
    last_tool_result_sha256: str | None = None
    final_agent_result_sha256: str | None = None


@dataclass(frozen=True)
class LoopGridRunSnapshot:
    run_id: str
    decision_id: str
    model_turns: int
    final_agent_result_sha256: str | None = None
    last_tool_result_sha256: str | None = None


class LoopGridPlugin(Plugin):
    """Native Strands plugin that records consequential agent evidence in LoopGrid.

    The plugin observes Strands lifecycle facts through native hooks. Application-owned
    semantics (delegated authority, policy, review, and business outcome) remain explicit.

    A completed Strands invocation is intentionally *not* treated as a successful business
    outcome. Call :meth:`observe_outcome` only after the application actually observes the
    external result.
    """

    name = "loopgrid-evidence"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        workspace_id: str | None = None,
        service_name: str = "strands-agents",
        agent_version: str = "0.1.0",
        decision_type: str = "strands_agent_run",
        privacy_mode: str = "redacted",
        authority: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        proposed_action: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        capture_content: bool = False,
        fail_open: bool = False,
        client: LoopGrid | None = None,
    ) -> None:
        base_url = base_url or os.getenv("LOOPGRID_BASE_URL", "http://127.0.0.1:8000")
        api_key = api_key or os.getenv("LOOPGRID_API_KEY")
        workspace_id = workspace_id or os.getenv("LOOPGRID_WORKSPACE_ID", "default")
        self.grid = client or LoopGrid(base_url=base_url, api_key=api_key, workspace_id=workspace_id)
        self.workspace_id = workspace_id
        self.service_name = service_name
        self.agent_version = agent_version
        self.decision_type = decision_type
        self.privacy_mode = privacy_mode
        self.authority = dict(authority or {})
        self.policy = dict(policy or {})
        self.proposed_action = dict(proposed_action or {})
        self.context = dict(context or {})
        self.capture_content = bool(capture_content)
        self.fail_open = bool(fail_open)
        self._runs: dict[str, _RunState] = {}
        self._lock = threading.RLock()

        # Strands Plugin.__init__ discovers @hook-decorated methods and
        # initializes the native _hooks/_tools registries used by Agent.
        super().__init__()

    def _call(self, fn, /, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            if self.fail_open:
                return None
            raise

    def _lg_state(self, invocation_state: dict[str, Any]) -> dict[str, Any]:
        raw = invocation_state.get("loopgrid")
        if raw is None:
            raw = {}
            invocation_state["loopgrid"] = raw
        if not isinstance(raw, dict):
            raise TypeError("invocation_state['loopgrid'] must be a dictionary")
        return raw

    def _run(self, run_id: str) -> _RunState:
        with self._lock:
            state = self._runs.get(str(run_id))
        if state is None:
            raise KeyError(f"No LoopGrid decision recorded for Strands run {run_id!r}")
        return state

    def decision_id_for(self, run_id: str) -> str | None:
        with self._lock:
            state = self._runs.get(str(run_id))
            return state.decision_id if state else None

    def snapshot_for(self, run_id: str) -> LoopGridRunSnapshot | None:
        with self._lock:
            state = self._runs.get(str(run_id))
            if state is None:
                return None
            return LoopGridRunSnapshot(
                run_id=state.run_id,
                decision_id=state.decision_id,
                model_turns=state.model_turn,
                final_agent_result_sha256=state.final_agent_result_sha256,
                last_tool_result_sha256=state.last_tool_result_sha256,
            )

    def get_decision(self, run_id: str) -> dict[str, Any] | None:
        decision_id = self.decision_id_for(run_id)
        return self._call(self.grid.get_decision, decision_id) if decision_id else None

    def verify_workspace(self) -> dict[str, Any] | None:
        return self._call(self.grid.verify_workspace)

    def review_run(self, run_id: str, action: str, reviewer: str, reason: str = "") -> dict[str, Any] | None:
        if action not in {"approve", "reject"}:
            raise ValueError("action must be 'approve' or 'reject'")
        state = self._run(run_id)
        return self._call(self.grid.review, state.decision_id, action, reviewer, reason)

    def record_policy(self, run_id: str, policy: Mapping[str, Any]) -> dict[str, Any] | None:
        state = self._run(run_id)
        with self._lock:
            if state.policy_recorded:
                raise RuntimeError("Production policy evidence is already recorded for this Strands run")
            payload = _policy_payload(policy)
            state.policy = dict(payload)
        result = self._call(
            self.grid.add_event,
            state.decision_id,
            "policy_evaluated",
            payload,
            "policy",
            str(payload.get("policy_id") or "application-policy"),
            idempotency_key=f"strands:{run_id}:policy",
        )
        if result is not None or not self.fail_open:
            with self._lock:
                state.policy_recorded = True
        return result

    def observe_outcome(
        self,
        run_id: str,
        outcome: Mapping[str, Any] | Any,
        *,
        observer_id: str = "application",
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        state = self._run(run_id)
        projected = _jsonable(outcome)
        payload = dict(projected) if isinstance(projected, dict) else {"value": projected}
        payload.setdefault("framework", "strands-agents")
        payload.setdefault("run_id", run_id)
        if state.final_agent_result_sha256:
            payload.setdefault("agent_result_sha256", state.final_agent_result_sha256)
        if state.last_tool_result_sha256:
            payload.setdefault("last_tool_result_sha256", state.last_tool_result_sha256)
        return self._call(
            self.grid.add_event,
            state.decision_id,
            "outcome_observed",
            payload,
            "system",
            observer_id,
            idempotency_key=idempotency_key or f"strands:{run_id}:outcome:{_sha256(payload)[:24]}",
        )

    def _ensure_policy(self, state: _RunState) -> None:
        if state.policy and not state.policy_recorded:
            self.record_policy(state.run_id, state.policy)

    @hook
    def before_invocation(self, event: BeforeInvocationEvent) -> None:
        invocation_state = event.invocation_state
        lg = self._lg_state(invocation_state)
        run_id = str(lg.get("run_id") or uuid.uuid4().hex)
        lg["run_id"] = run_id

        authority = dict(self.authority)
        authority.update(dict(lg.get("authority") or {}))
        policy = dict(self.policy)
        policy.update(dict(lg.get("policy") or {}))
        proposed_action = dict(self.proposed_action)
        proposed_action.update(dict(lg.get("proposed_action") or {}))
        app_context = dict(self.context)
        app_context.update(dict(lg.get("context") or {}))

        agent = event.agent
        agent_id = str(getattr(agent, "agent_id", None) or getattr(agent, "name", None) or "strands-agent")
        agent_name = str(getattr(agent, "name", None) or agent_id)
        model = _model_provenance(agent)
        messages_projection = _jsonable(event.messages)
        context = {
            "framework": "strands-agents",
            "framework_version": _strands_version(),
            "run_id": run_id,
            "agent_name": agent_name,
            "capture_content": self.capture_content,
            "application": app_context,
        }
        input_evidence: dict[str, Any] = {
            "messages_sha256": _sha256(messages_projection),
            "message_count": len(event.messages or []),
        }
        if self.capture_content:
            input_evidence["messages"] = messages_projection

        result = self._call(
            self.grid.record_decision,
            decision_type=self.decision_type,
            service_name=self.service_name,
            workspace_id=self.workspace_id,
            privacy_mode=self.privacy_mode,
            idempotency_key=f"strands:{run_id}:decision",
            agent={"id": agent_id, "name": agent_name, "version": self.agent_version},
            authority=authority,
            model=model,
            context=context,
            input=input_evidence,
            proposed_action=proposed_action,
            metadata={
                "source": "loopgrid-strands",
                "integration_version": "0.1.0",
                "capture_content": self.capture_content,
                "loopgrid_executes_external_action": False,
            },
        )
        if result is None:
            return
        decision_id = str(result["decision_id"])
        lg["decision_id"] = decision_id
        with self._lock:
            self._runs[run_id] = _RunState(
                decision_id=decision_id,
                run_id=run_id,
                agent_id=agent_id,
                model=model,
                policy=policy,
            )

    @hook
    def after_model(self, event: AfterModelCallEvent) -> None:
        lg = self._lg_state(event.invocation_state)
        run_id = str(lg.get("run_id") or "")
        if not run_id or not self.decision_id_for(run_id):
            return
        state = self._run(run_id)

        if event.exception is not None:
            payload = _event_error_payload(event.exception, framework="strands-agents", run_id=run_id, stage="model")
            self._call(
                self.grid.add_event,
                state.decision_id,
                "incident_flagged",
                payload,
                "integration",
                "loopgrid-strands",
                idempotency_key=f"strands:{run_id}:model-error:{_sha256(payload)[:24]}",
            )
            return

        if event.stop_response is None:
            return
        with self._lock:
            state.model_turn += 1
            model_turn = state.model_turn
        message_projection = _jsonable(event.stop_response.message)
        payload: dict[str, Any] = {
            "framework": "strands-agents",
            "run_id": run_id,
            "model_turn": model_turn,
            "model": state.model,
            "stop_reason": str(event.stop_response.stop_reason),
            "message_sha256": _sha256(message_projection),
            "retry_requested_at_capture": bool(getattr(event, "retry", False)),
        }
        if self.capture_content:
            payload["message"] = message_projection
        self._call(
            self.grid.add_event,
            state.decision_id,
            "model_completed",
            payload,
            "agent",
            state.agent_id,
            idempotency_key=f"strands:{run_id}:model:{model_turn}",
        )
        # A response already marked for retry is not the accepted model decision.
        # Record the framework fact, but wait for an accepted model response before
        # appending caller-owned policy evidence.
        if not bool(getattr(event, "retry", False)):
            self._ensure_policy(state)

    @hook
    def before_tool(self, event: BeforeToolCallEvent) -> None:
        lg = self._lg_state(event.invocation_state)
        run_id = str(lg.get("run_id") or "")
        if not run_id or not self.decision_id_for(run_id):
            return
        state = self._run(run_id)
        self._ensure_policy(state)
        tool_use = dict(event.tool_use or {})
        tool_name = str(tool_use.get("name") or getattr(event.selected_tool, "tool_name", None) or "unknown-tool")
        tool_use_id = str(tool_use.get("toolUseId") or uuid.uuid4().hex)
        with self._lock:
            attempt = state.tool_attempt_by_id.get(tool_use_id, 0) + 1
            state.tool_attempt_by_id[tool_use_id] = attempt
        tool_input = _jsonable(tool_use.get("input"))
        payload: dict[str, Any] = {
            "framework": "strands-agents",
            "run_id": run_id,
            "tool": tool_name,
            "tool_use_id": tool_use_id,
            "attempt": attempt,
            "input_sha256": _sha256(tool_input),
        }
        if self.capture_content:
            payload["input"] = tool_input
        self._call(
            self.grid.add_event,
            state.decision_id,
            "tool_requested",
            payload,
            "agent",
            "strands-agent",
            idempotency_key=f"strands:{run_id}:tool:{tool_use_id}:attempt:{attempt}:requested",
        )

    @hook
    def after_tool(self, event: AfterToolCallEvent) -> None:
        lg = self._lg_state(event.invocation_state)
        run_id = str(lg.get("run_id") or "")
        if not run_id or not self.decision_id_for(run_id):
            return
        state = self._run(run_id)
        tool_use = dict(event.tool_use or {})
        tool_name = str(tool_use.get("name") or getattr(event.selected_tool, "tool_name", None) or "unknown-tool")
        tool_use_id = str(tool_use.get("toolUseId") or "unknown")
        with self._lock:
            attempt = state.tool_attempt_by_id.get(tool_use_id, 1)
        result = event.result
        result_projection = _jsonable(result)
        result_sha = _sha256(result_projection)
        with self._lock:
            state.last_tool_result_sha256 = result_sha

        cancelled = bool(getattr(event, "cancel_message", None))
        result_status = result.get("status") if isinstance(result, Mapping) else None
        if isinstance(result, BaseException) or cancelled or result_status == "error":
            error_type = type(result).__name__ if isinstance(result, BaseException) else ("ToolCancelled" if cancelled else "ToolError")
            error_source = str(result) if isinstance(result, BaseException) else (str(getattr(event, "cancel_message", "")) or json.dumps(result_projection, sort_keys=True))
            payload = {
                "framework": "strands-agents",
                "run_id": run_id,
                "tool": tool_name,
                "tool_use_id": tool_use_id,
                "attempt": attempt,
                "status": "cancelled" if cancelled else "failed",
                "error_type": error_type,
                "error_sha256": _sha256(error_source),
                "result_sha256": result_sha,
                "retry_requested_at_capture": bool(getattr(event, "retry", False)),
            }
            if self.capture_content:
                payload["result"] = result_projection
            self._call(
                self.grid.add_event,
                state.decision_id,
                "tool_result",
                payload,
                "tool",
                tool_name,
                idempotency_key=f"strands:{run_id}:tool:{tool_use_id}:attempt:{attempt}:{payload['status']}",
            )
            return

        payload = {
            "framework": "strands-agents",
            "run_id": run_id,
            "tool": tool_name,
            "tool_use_id": tool_use_id,
            "attempt": attempt,
            "status": "executed",
            "result_sha256": result_sha,
            "cancelled": bool(getattr(event, "cancel_message", None)),
            "retry_requested_at_capture": bool(getattr(event, "retry", False)),
            "executor": "strands-agent-runtime",
        }
        if self.capture_content:
            payload["result"] = result_projection
        self._call(
            self.grid.add_event,
            state.decision_id,
            "tool_executed",
            payload,
            "tool",
            tool_name,
            idempotency_key=f"strands:{run_id}:tool:{tool_use_id}:attempt:{attempt}:executed",
        )

    @hook
    def after_invocation(self, event: AfterInvocationEvent) -> None:
        lg = self._lg_state(event.invocation_state)
        run_id = str(lg.get("run_id") or "")
        if not run_id or not self.decision_id_for(run_id):
            return
        if event.result is None:
            return
        state = self._run(run_id)
        result_hash = _sha256(event.result)
        with self._lock:
            state.final_agent_result_sha256 = result_hash
        lg["agent_result_sha256"] = result_hash
