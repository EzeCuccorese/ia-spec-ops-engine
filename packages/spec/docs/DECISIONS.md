# Decision Log

## 2026-08-25 — Parallel clean-room implementation

The v2 is built under `next/`. Legacy code is reference material only and remains available until
the new implementation passes its safety and daily-workflow gates.

## 2026-08-25 — Personal tool, not public platform

Optimize for one real user and actual workflows. Public packaging, broad compatibility, and
commercial positioning are not current goals.

## 2026-08-25 — Governance and SDD only

The `spec` CLI owns policy, specifications, verification, evidence, and agent adapters. DevOps,
Kubernetes, local-service orchestration, and workspace provisioning are not optional CLI domains:
they are outside the product and frozen under `spec-devops/`.

## 2026-08-25 — Experiments are explicit

Multi-agent and self-healing loops live behind an `experiment` namespace until evidence supports
promotion.

## 2026-08-26 — Codex adapter uses the discovered file or refuses

Codex discovers one instruction file per directory, preferring `AGENTS.override.md` and then
`AGENTS.md`; an arbitrary generated filename is not reliably active without global fallback
configuration. Spec therefore creates a repository-root `AGENTS.md` only when absent or already
owned. It refuses an existing unowned file instead of silently replacing it or mutating global
Codex configuration. Source: [official OpenAI AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
