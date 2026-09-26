# Windows release-candidate test

PowerShell:

```powershell
cd C:\Loop\loopgrid-strands-v0.1.0\loopgrid-strands
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -c "import importlib.metadata as m; print('strands-agents:', m.version('strands-agents')); print('loopgrid:', m.version('loopgrid')); print('loopgrid-strands:', m.version('loopgrid-strands'))"
python -m pytest -v
python -m compileall -q src examples tests
```

Then ensure LoopGrid Core is running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
```

Set credentials in the same PowerShell session (do not paste them into chat):

```powershell
$env:LOOPGRID_BASE_URL="http://127.0.0.1:8000"
$env:LOOPGRID_WORKSPACE_ID="default"
$env:LOOPGRID_API_KEY="YOUR_EXISTING_LG_LIVE_KEY"
```

Run:

```powershell
python examples\refund_gate.py
```

Release gate: lifecycle `evidence_complete`, coverage `100`, verify `valid: true`, failures `[]`.
