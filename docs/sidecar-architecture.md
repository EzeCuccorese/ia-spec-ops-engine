# Sidecar Architecture

AI Agent Yolo runs agents in an isolated container with minimal permissions.
Anything that requires elevated access — Docker, API keys, cloud credentials —
lives in a dedicated **sidecar container** started alongside claude-yolo.

## Concepts

- **claude-yolo** — the main agent container. No Docker socket. No secrets. Talks to sidecars over HTTP on the internal Docker network.
- **Sidecar** — a purpose-built container with exactly the access it needs. Exposes a simple HTTP API. Started and stopped by `claude-yolo.sh`.
- **Workspace network** — a Docker bridge network named `<workspace-name>-net`. All containers in the workspace join it automatically. Containers reach each other by container name.

## Directory layout for a new sidecar

```
docker/
└── <sidecar-name>/
    ├── Dockerfile        # minimal image — only what the sidecar needs
    ├── server.py         # HTTP server (or server.sh for simple cases)
    ├── sidecar.sh        # start_<sidecar_name>_sidecar function
    └── tests/            # unit tests for the server logic
```

`sidecar.sh` is the only file `claude-yolo.sh` knows about.

## The cleanup stack

`claude-yolo.sh` owns a single EXIT trap via `_run_cleanups`. Sidecars must never call `trap` directly — they push cleanup commands onto `_CLEANUP_CMDS`:

```bash
_CLEANUP_CMDS+=("docker rm -f '$CONTAINER_NAME' 2>/dev/null || true")
```

Commands run in reverse push order when the shell exits. The stack is bash 3.2 safe.

## The `sidecar.sh` contract

Every sidecar exposes one bash function named `start_<sidecar_name>_sidecar`.
The function:

1. Reads these variables from the caller's scope (set by `claude-yolo.sh` before calling):
   - `WORKSPACE_DIR` — absolute path to the workspace root
   - `WORKSPACE_NAME` — name of the current workspace
   - `REPOS_DIR` — absolute host path to the workspace's `repositories/` directory
   - `AI_DIR` — absolute host path to the workspace's `.ai-toolkit/` directory
   - `_CLEANUP_CMDS` — the cleanup stack array

2. Sets in the caller's scope:
   - `NETWORK_NAME` — Docker network name. The **first** sidecar creates the network; subsequent sidecars call `docker network create "$NETWORK_NAME" 2>/dev/null || true` (idempotent). `claude-yolo.sh` reads this after the call to pass `--network "$NETWORK_NAME"` to the workspace container.
   - `<SIDECAR_NAME>_URL` — HTTP base URL reachable inside claude-yolo (e.g. `TEST_RUNNER_URL`)

3. Handles its own:
   - Image tag computation (content hash of its directory)
   - Image build if missing
   - Container start with `--network "$NETWORK_NAME"`
   - Cleanup push (never direct `trap`)
   - Readiness wait (`docker inspect --format '{{.State.Health.Status}}'` until `healthy`)

## Wiring a new sidecar into `claude-yolo.sh`

Three lines only:

```bash
# 1. Source the sidecar definition (after existing sources)
source "$WORKSPACE_DIR/docker/<sidecar-name>/sidecar.sh"

# 2. Start the sidecar (before the main docker run)
start_<sidecar_name>_sidecar

# 3. Pass the URL into claude-yolo (inside the docker run flags)
-e "<SIDECAR_NAME>_URL=$<SIDECAR_NAME>_URL" \
```

## HTTP interface

Every sidecar must implement:

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Returns `{"status":"ok"}` with HTTP 200. Must be wired to the Dockerfile `HEALTHCHECK`. |
| `/<action>` | POST | Sidecar-specific action. Body: JSON. Response: streaming `application/x-ndjson`. |

### Response conventions

- `GET /health` returns `Content-Type: application/json` with `Content-Length`.
- `POST /<action>` streams output: plain text lines, then a final JSON line `{"exit_code": N}`. No `Content-Length` — connection closes when the handler returns.
- The agent reads with `curl -sN`, prints non-`{"exit_code":` lines to stdout, captures the last JSON line for the exit code.

### Dockerfile HEALTHCHECK

Every sidecar Dockerfile must include a HEALTHCHECK on `/health` so `claude-yolo.sh` can wait for readiness:

```dockerfile
HEALTHCHECK --interval=2s --timeout=3s --start-period=5s --retries=10 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:<PORT>/health').read()" || exit 1
```

## Repos without a Dockerfile

Sidecars that run tests (like test-runner) must handle repos with no Dockerfile. The toolkit's `detect_prebuild.py` supports a 1-arg repo-only mode: it detects the right runner image from filesystem markers (`package.json` → `node:20`, `gradlew` → `eclipse-temurin:21-jdk-jammy`, `go.mod` → `golang:1.24`) without reading any Dockerfile. Pass `dockerfile=None` to `get_prebuild_info` and it will use this mode automatically. For JVM repos the **declared** Java version is used as-is — no LTS remapping (JaCoCo and other bytecode tooling pin to the runtime JDK). The script emits an ordered candidate list — the declared JDK across Ubuntu codenames (`focal`/`jammy`/`noble`) plus the repo's Dockerfile base — that the shell validates against the registry (`docker manifest inspect`), using the first that exists. So JDK 20 lands on `20-jdk-jammy` (no `-focal` exists).

## Mirror mounts

Sidecars that run `docker` commands (like test-runner) need **mirror mounts**: repos mounted at the same absolute path inside the sidecar as on the host. This lets the sidecar pass host-valid paths to `docker run -v`.

```bash
local repo_mounts=()
for repo_dir in "$REPOS_DIR"/*/; do
  repo_dir="${repo_dir%/}"
  [[ -d "$repo_dir" ]] || continue
  repo_mounts+=("-v" "$repo_dir:$repo_dir")
done
```

Sidecars that only call APIs (Jira, GitHub) do **not** need mirror mounts.

## Image tagging

Content hashes of the sidecar directory. Add a helper to `docker/scripts/docker-utils.sh`:

```bash
_get_<sidecar_name>_image_tag() {
  local toolkit_dir="$1"
  if command -v shasum &>/dev/null; then
    find "$toolkit_dir/docker/<sidecar-name>" -type f -exec shasum -a 256 {} + | sort | shasum -a 256 | cut -c1-12
  else
    find "$toolkit_dir/docker/<sidecar-name>" -type f -exec sha256sum {} + | sort | sha256sum | cut -c1-12
  fi
}
```

## Persistent test containers

Test-runner manages one container per repo per workspace session. Key choices:

- `--init` on every `docker run` — PID 1 handles signals and reaps zombies from `docker exec` processes
- `sleep infinity` as the keep-alive command — cleaner than `tail -f /dev/null`, responds to SIGTERM
- Per-repo `threading.Lock` in Python — repos build/start independently; one slow Gradle build does not block a Node test run
- `ThreadingHTTPServer` — one thread per request; concurrent repos run in parallel

## Port registry

| Sidecar | Port |
|---|---|
| test-runner | 7070 |
| _(next sidecar)_ | 7071 |
| _(next sidecar)_ | 7072 |
