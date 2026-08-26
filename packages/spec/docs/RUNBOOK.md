# Spec v2 Runbook

## Local development

```bash
PYTHONPATH=next/src python -m pytest next/tests -q
PYTHONPATH=next/src python -m spec doctor --json
```

No installation is required. The runtime has no third-party dependency.

## Initialize a project

```bash
PYTHONPATH=next/src python -m spec init --root /path/to/project
PYTHONPATH=next/src python -m spec agent install --root /path/to/project
```

`agent install` creates the real root `AGENTS.md` Codex discovers. If that file already exists and
Spec does not own it, the command stops and preserves it. Manual reconciliation is required.

## Configure verification

Edit `.spec/verification.json`:

```json
{
  "schema_version": 1,
  "checks": [
    {
      "id": "tests",
      "command": ["python", "-m", "pytest", "-q"],
      "required": true,
      "timeout_seconds": 300
    }
  ]
}
```

Commands must be non-empty JSON string arrays. Shell strings are rejected. Check IDs must match
`[a-z0-9][a-z0-9_-]*`, timeouts are limited to 1–3600 seconds, and IDs must be unique.

## Result and exit-code contract

| Report | Meaning | `spec verify` exit |
| --- | --- | --- |
| `PASS` | Every required check passed | 0 |
| `FAIL` | A required command returned non-zero | 1 |
| `INCOMPLETE` | Required check missing/skipped or no checks configured | 2 |
| `ERROR` | Required check could not complete, including timeout | 2 |

Optional failed checks remain visible in evidence but do not change the aggregate required status.
Stdout and stderr are capped at 8,000 characters per stream.

## Resume and retry

`spec status --json --root /path/to/project` reads the persisted stage without mutation. After a
failed/incomplete verification, fix code or configuration and run `spec verify` again. Never edit
state or evidence manually.

## Remove the adapter

```bash
# Preview only
PYTHONPATH=next/src python -m spec agent uninstall --root /path/to/project

# Apply after digest validation
PYTHONPATH=next/src python -m spec agent uninstall --apply --root /path/to/project
```

If the generated `AGENTS.md` changed, removal stops to preserve the user's edits.
