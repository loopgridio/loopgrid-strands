# Security

## Credentials

Use `LOOPGRID_API_KEY` through environment/secrets management. Never commit service keys.

## Raw content

`capture_content=False` is the default. Prompt/model/tool/error content is commitment-hashed rather than stored in raw form. Turning raw capture on is an application privacy decision.

## Authority and policy

The plugin does not derive authority or policy from agent telemetry. Supply them from your application/control plane.

## Execution

LoopGrid does not execute Strands tools. A `tool_executed` event means Strands reported completion of the tool invocation; it is evidence of execution in that runtime, not independent proof that an external business system settled the action. Record `outcome_observed` only after the application observes the external result.

## Review scope

A LoopGrid service key with `review` scope is required if `review_run()` is used. Ordinary capture/read workflows should use the minimum required scopes.

## Reporting

Please report security issues privately through the security contact/process published by LoopGrid rather than opening a public issue containing sensitive details.
