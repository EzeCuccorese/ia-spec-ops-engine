# Current limitations

These are deliberate boundaries, not hidden roadmap claims.

- Only the Codex `AGENTS.md` adapter exists. No Claude, Cursor, Gemini, MCP, or global adapter is
  implemented.
- Spec does not generate implementation code or autonomously operate agents.
- There is no multi-agent orchestrator, self-healing loop, semantic spec reviewer, or AI audit.
- Verification runs user-configured local commands; it does not provide an OS sandbox.
- Policy JSON records the local contract and the adapter ships corresponding fixed guidance, but a
  dynamic policy rule engine is not implemented.
- Specs, plans, and tasks are structural templates; content quality remains a human/agent review.
- No Git staging, commit, push, branch, PR, worktree, Kubernetes, build, or environment management
  is part of v2.
- There is no global installer or global cleanup command.

An experiment must live outside stable CLI commands and earn promotion through repeatable tests
against real personal workflows. No experimental command is currently shipped.
