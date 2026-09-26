# Integration contract

LoopGrid Strands v0.1.0 is intentionally thin and framework-native.

## LoopGrid API contract

It uses the existing LoopGrid Core contract only:

- `POST /api/v1/decisions`
- `POST /api/v1/decisions/{decision_id}/events`
- `POST /api/v1/decisions/{decision_id}/review`
- `GET /api/v1/decisions/{decision_id}`
- `GET /api/v1/integrity/verify`
- `X-LoopGrid-Key` authentication

No Strands-specific Core endpoints are introduced.

## Evidence ownership

Observed automatically from native Strands hooks:
- invocation/run identity
- agent identity
- model provenance
- successful model completion
- tool request
- tool execution/result
- framework errors

Explicit caller-owned evidence:
- delegated authority
- policy decision/provenance
- human approval/rejection
- business outcome

The plugin never infers authority, approval, policy, or business success from a trace.

## Enforcement boundary

The plugin does not cancel tools, alter model responses, execute refunds/payments, or decide policy. Use Strands interventions/hooks or application code for enforcement. LoopGrid records the signed evidence of what was authorized, decided, executed, and observed.
