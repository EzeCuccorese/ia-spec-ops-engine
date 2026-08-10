# Sidecar Architecture

The agent environment runs in an isolated container with minimal permissions.
Anything requiring elevated access — Docker, API keys, cloud credentials —
lives in a dedicated **sidecar container** started alongside the main agent.

## Concepts

- **Agent Container** — the main workspace. No Docker socket. No secrets. Communicates with sidecars over HTTP on the internal Docker network.
- **Sidecar** — a purpose-built container with exactly the access it needs. Exposes a simple HTTP API. Managed dynamically via the Python orchestration layer.
- **Workspace Network** — a Docker bridge network named `<workspace-name>-net`. All containers in the workspace join it automatically.

## 100% Python Orchestration

The architecture is built on a **100% Python cross-platform architecture** (0% `.sh`, 0% `.bat`, 0% `.bats`), working natively on Windows, macOS, and Linux.

The orchestrator creates sidecars, handles container networking, and cleans up resources via context managers or explicit `try/finally` blocks, replacing legacy script-based traps.

## Directory Layout for a New Sidecar

```
docker/
└── <sidecar-name>/
    ├── Dockerfile        # minimal image — only what the sidecar needs
    ├── server.py         # HTTP server
    ├── sidecar.py        # Python module defining Sidecar orchestration class
    └── tests/            # unit tests for the server logic
```

## Sidecar Contract

Every sidecar implements a Python class inheriting from a base `Sidecar` abstract class.
The class handles:
- Deriving its image tag (content hash of its directory).
- Building the image if missing.
- Starting the container with `--network "<workspace-name>-net"`.
- Reporting readiness by polling the `HEALTHCHECK` endpoint.
- Registering cleanup routines in the orchestrator.

## HTTP Interface

Every sidecar must implement:

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Returns `{"status":"ok"}` with HTTP 200. Used for Docker `HEALTHCHECK`. |
| `/<action>` | POST | Sidecar-specific action. Body: JSON. Response: streaming `application/x-ndjson`. |

### Response Conventions

- `GET /health` returns `Content-Type: application/json` with `Content-Length`.
- `POST /<action>` streams output: plain text lines, then a final JSON line `{"exit_code": N}`. 

## End-to-End Adaptation

Sidecars automatically adjust their context and output format based on the **Dynamic End-to-End AI Agent adaptation matrix**. Supported agents include:
- Antigravity 2.0
- Gemini CLI
- Claude Code
- GitHub Copilot
- Cursor
- ChatGPT
