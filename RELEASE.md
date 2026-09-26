# v0.1.0 release gate

Do not tag/publish until:

- `python -m pytest -v` passes with the installed current Strands dependency.
- `python -m compileall -q src examples tests` passes.
- canonical demo passes against LoopGrid Core `0.8.1-design-partner`.
- demo ends with `evidence_complete`, `coverage=100`, `verification.valid=true` and no verification failures.
- GitHub Actions is green on `main`.
- public README accurately describes only validated behavior.

Then:

```bash
git tag -a v0.1.0 -m "LoopGrid Strands integration v0.1.0"
git push origin v0.1.0
python -m build
```

Publish PyPI package `loopgrid-strands`, create the GitHub release, add the LoopGrid integration page, then submit the Strands catalog entry.
