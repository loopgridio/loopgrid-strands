# Validation plan — v0.1.0

A release is not considered validated until all gates pass.

1. Unit tests — hashing/privacy, per-run overrides, policy semantics, review helper, failed tools, fail-open behavior.
2. Native Strands runtime test — real `Agent`, native `Plugin`, native hooks, native decorated tool, deterministic custom `Model`; no network/model provider.
3. Python compile check.
4. Local LoopGrid Core `0.8.1-design-partner` E2E with the canonical sandbox demo.
5. Expected E2E result: lifecycle `evidence_complete`, evidence coverage `100`, verification `valid=true`, failures `[]`.
6. GitHub Actions green before tag.
7. PyPI publication from the tagged source.
8. Strands integrations catalog PR only after the package/repo are public.

Do not claim Strands/AWS verification, endorsement, partner status, Featured status, or badge unless the Strands maintainers explicitly grant it.

## Strands Python invocation-state note

`invocation_state` is the request-scoped channel consumed by native Strands hooks and tools.
Do not read the LoopGrid `run_id` back from `AgentResult.state`; current Python Strands uses
that field for its event-loop/request-state slot. Keep the caller-owned `run_id` explicitly and
use it with `LoopGridPlugin.observe_outcome(...)`. The runtime test covers this behavior.
