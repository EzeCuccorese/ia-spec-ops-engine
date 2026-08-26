# Architecture

Spec v2 has four one-way layers:

1. `core`: path boundaries, atomic writes, ownership, and result contracts.
2. `governance` and `spec`: repository policy and the SDD state machine.
3. `verify`: explicit command execution and immutable evidence.
4. `adapters` and `cli`: agent-specific rendering and user interaction.

Agent adapters depend on the core; the core never depends on Codex or another agent. DevOps code
is not a layer and cannot be imported by v2.

## Repository-local state

| Path | Purpose | Mutable by user |
| --- | --- | --- |
| `.spec/policy.json` | Product boundary and governance invariants | Yes |
| `.spec/verification.json` | Explicit verification argv and requirements | Yes |
| `.spec/state.json` | Recoverable active workflow snapshot | No |
| `.spec/specs/<feature>/` | Spec, plan, and task artifacts | Yes |
| `.spec/evidence/<feature>/` | Immutable verification reports | No |
| `.spec/ownership.json` | Digests of files Spec may update/delete | No |
| `AGENTS.md` | Codex adapter, only when Spec created it | No |

State and manifests are written to a temporary file in the same directory, flushed, and atomically
replaced. Specs, plans, tasks, and evidence use exclusive creation and are never overwritten.

## State machine

`SPEC -> PLAN -> TASKS -> WORK -> VERIFY -> COMPLETE`

Transitions validate the preceding non-empty artifact. Verification may be repeated from `VERIFY`;
each attempt creates a new evidence file and updates the state pointer. `COMPLETE` requires the last
recorded report to be `PASS` and its evidence file to exist.

## Trust boundary

Spec guarantees how configured checks are launched and reported; it does not sandbox the commands
the user explicitly configures. Those commands run with the current user's permissions, with the
project root as working directory and stdin disabled.
