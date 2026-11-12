# ia-spec-ops-engine

This repository contains two independently installable Python packages:

- `packages/ai-governance`: rules, task flow (taskflow), telemetry, context-frugality tools, and Atlassian utilities.
- `packages/workspace`: deterministic quality gates (`ws check`, `ws hooks`), design limits (`ws design`), stack detection (`ws detect`), and command condensation (`ws run`, `ws condense`, `ws log`).

The checkout is a source repository, not a bootstrap script. Do not install packages, create virtual environments, configure an agent, or write project configuration unless the user explicitly asks for that action and names the package or component to install.

When the user asks to adopt a capability, inspect its package first, describe the available scopes, and install only the requested scope. Preserve unrelated user configuration.

Use English for documentation, CLI output, and user-facing messages.

When a selected environment already exists, verify relevant changes with its available Python tooling and tests. Do not create an environment merely to run checks unless the user asks.
