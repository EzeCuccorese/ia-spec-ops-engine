# Kubernetes & Cloud-Native Invariants

## Invariants
- **Health Probes**: Configure `startupProbe` for slow boot, `readinessProbe` for traffic acceptance, and `livenessProbe` for deadlocks.
- **Graceful Shutdown**: Handle `SIGTERM` signals, flush in-flight requests, and wait with a `preStop.exec.sleep` hook during pod eviction.
- **Resource Limits**: Define explicit CPU and Memory `requests` and `limits` on every container to prevent `OOMKilled` events.
- **Security Context**: Enforce `readOnlyRootFilesystem: true` and drop unnecessary Linux capabilities (`drop: [ALL]`).
