# Strands integrations catalog submission

Submit only after GitHub + PyPI + LoopGrid docs are public and v0.1.0 is validated.

Current Strands submission flow:
1. Fork `strands-agents/harness-sdk`.
2. Add `site/src/content/catalog/loopgrid-strands.yaml`.
3. Open a PR with the integration submission template.

Proposed catalog entry:

```yaml
name: loopgrid-strands
description: Signed, independently verifiable evidence for consequential Strands agent decisions, actions, reviews, and outcomes.
integrationType: plugin
languages:
  python:
    package: loopgrid-strands
github: https://github.com/loopgridio/loopgrid-strands
docsUrl: https://loopgrid.io/integrations/strands/
addedDate: 2026-09-27
```

`maintainedBy: partner` may be requested only if the Strands maintainers confirm the LoopGrid GitHub organization qualifies as the official company organization. Do not set `featured` or `badges`; those are granted by Strands maintainers.
