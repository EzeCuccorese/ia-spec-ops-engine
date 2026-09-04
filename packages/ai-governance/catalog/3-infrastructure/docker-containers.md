# Docker & Container Security

## Invariants
- **Multi-Stage Builds**: Use multi-stage builds to produce minimal runtime artifacts without build toolchains.
- **Non-Root Execution**: Always run containers as a non-privileged user (`USER nonroot:nonroot` or `USER 10001`).
- **Minimal Base Images**: Use official, minimal base images (Distroless, Alpine, Chainguard).
- **Zero Secrets in Images**: Prohibit storing credentials or private keys in `ENV`, `ARG`, or image layers.
