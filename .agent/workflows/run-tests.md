---
description: How to run the test suite
---

# Running Tests

> [!CAUTION]
> **DO NOT** pipe pytest through `Select-Object -Last` in PowerShell.  
> This causes a deadlock because `Select-Object -Last N` buffers all input, filling the pipe buffer and blocking pytest from writing.
>
> ❌ `python -m pytest tests/ -q --tb=line 2>&1 | Select-Object -Last 20` — **WILL HANG**
>
> ✅ Use these instead:

// turbo-all

1. Run tests directly (recommended):
```powershell
python -m pytest tests/ -q --tb=line
```

2. If you only want the last N lines, write to temp file first:
```powershell
python -m pytest tests/ -q --tb=line *> $env:TEMP\pytest.log; cat $env:TEMP\pytest.log -Tail 20
```
