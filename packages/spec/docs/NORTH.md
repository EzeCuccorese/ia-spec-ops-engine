# Spec North

## Purpose

Spec is Eze's personal operating layer for coding agents. It turns intent into versioned
artifacts, supplies relevant repository rules, runs deterministic checks, and records evidence
without taking control away from the user.

## Primary job

When delegating code changes to an agent, make the expected result explicit and verify the
outcome without risking unrelated files, repositories, credentials, or Git history.

## Core loop

`Idea -> Spec -> Plan -> Tasks -> Work -> Verify -> Finish`

The loop may be shortened for small work, but no command may claim that work happened when it
only updated state or printed instructions.

## In scope

- One local CLI: `spec`.
- Repository-local specifications, policies, state, and evidence.
- Strict verification results: `PASS`, `FAIL`, `INCOMPLETE`, `SKIPPED`, `ERROR`.
- Codex and `AGENTS.md` first; other adapters only when used in practice.
- Experiments isolated from stable commands.

## Out of scope

- A public SaaS or commercial developer platform.
- Universal support for every agent and operating system.
- Marketing claims without reproducible local evidence.
- Multi-agent complexity without a measured benefit.
- Global configuration mutation by default.
- Kubernetes, local-service orchestration, worktree provisioning, and environment management.
- General-purpose DevOps automation; the legacy implementation is frozen under `spec-devops/`.

## Non-negotiable invariants

1. Spec deletes only paths recorded in its ownership manifest.
2. A path must remain inside an explicit allowed root after resolving symlinks.
3. Existing user files are never silently overwritten.
4. Destructive operations provide a dry-run and resolved target list.
5. `SKIPPED` and missing tooling never silently become `PASS`.
6. State transitions require their corresponding artifact and validation evidence.
7. The core is independent from any particular coding agent.
8. Adapters translate Spec data; they do not own workflow logic.
9. Experiments cannot be invoked through stable commands accidentally.
10. Documentation describes current behavior, not aspirations.

## Success for a personal MVP

- A new task can reach its first meaningful verification in under ten minutes.
- Install and uninstall leave unrelated files byte-for-byte unchanged.
- Interrupted work can be resumed from repository state.
- Verification explains exactly what ran, what did not run, and why.
- The daily workflow removes more friction than it adds.
