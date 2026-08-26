# Spec v2

Spec is a personal, repository-local governance and Spec-Driven Development CLI for coding
agents. This clean-room implementation lives in `next/` until the cutover gate is accepted.

It implements one honest loop:

`init -> spec -> plan -> tasks -> work -> verify -> finish`

## Run without installing

From the repository root:

```bash
PYTHONPATH=next/src python -m spec --help
PYTHONPATH=next/src python -m pytest next/tests -q
```

Example against another local repository:

```bash
export CUCCO="PYTHONPATH=$PWD/next/src python -m spec"
$CUCCO init --root /path/to/project
$CUCCO agent install --root /path/to/project
$CUCCO spec new "My change" --description "Observable outcome" --root /path/to/project
$CUCCO plan --root /path/to/project
$CUCCO tasks --root /path/to/project
$CUCCO work --root /path/to/project
# Edit /path/to/project/.spec/verification.json with explicit argv checks.
$CUCCO verify --root /path/to/project
$CUCCO finish --root /path/to/project
```

`finish` succeeds only after all required verification checks pass. Missing tools, missing checks,
timeouts, skipped checks, and execution errors cannot be reported as `PASS`.

## Safety contract

- All writes and subprocess working directories stay below the explicit project root after
  symlink resolution.
- Generated adapter/config files are tracked by content digest.
- Spec will not overwrite an existing unowned `AGENTS.md`.
- Adapter removal defaults to dry-run and rejects user-modified generated files.
- Verification commands are JSON argv arrays and never pass through a shell.
- No command mutates global agent configuration, installs dependencies, pushes Git, or stages files.

Kubernetes, workspace provisioning, worktrees, builds, and local-service orchestration are outside
the product. Their legacy code is frozen under `../spec-devops/`.

## Documentation

- [`docs/NORTH.md`](docs/NORTH.md): product contract and invariants.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): boundaries and persisted data.
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md): commands, configuration, and recovery.
- [`docs/CUTOVER.md`](docs/CUTOVER.md): evidence required before deleting the legacy engine.
- [`docs/LEGACY-MATRIX.md`](docs/LEGACY-MATRIX.md): explicit keep/replace/reject decisions.
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md): current non-capabilities.
