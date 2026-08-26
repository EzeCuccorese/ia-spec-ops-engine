# Cucco

Cucco is being rebuilt as a personal AI-governance and Spec-Driven Development tool.

## Active implementation

The clean-room v2 is under [`next/`](next/). It is the only implementation on the active roadmap
and currently provides:

- one `cucco` CLI;
- repository-local governance policy;
- Spec → Plan → Tasks → Work → Verify → Finish lifecycle;
- strict verification with immutable evidence;
- safe paths, atomic writes, and explicit generated-file ownership;
- a reversible Codex `AGENTS.md` adapter;
- isolated unit and end-to-end tests.

Run it without installing anything:

```bash
PYTHONPATH=next/src python -m cucco --help
PYTHONPATH=next/src python -m pytest next/tests -q
```

See the [v2 README](next/README.md), [product north](next/docs/NORTH.md), and
[cutover plan](next/docs/CUTOVER.md).

## Legacy boundaries

- `packages/sdd/`, `packages/common/`, `rules/`, and the root installer are legacy reference
  material. They are not evidence of v2 behavior and are not used by the v2 runtime.
- Kubernetes, workspace provisioning, worktrees, builds, and local-service tooling are frozen in
  [`cucco-devops/`](cucco-devops/). They are outside the v2 product and no longer exposed by root
  packaging or scripts.

Do not delete the legacy governance engine until the real-work soak gate in the cutover plan is
complete.
