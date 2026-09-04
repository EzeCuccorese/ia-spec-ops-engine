# CI/CD & Supply Chain Security

## Invariants
- **Hermetic & Deterministic Builds**: Lock dependency versions via lockfiles (`package-lock.json`, `uv.lock`, `Cargo.lock`, `go.sum`).
- **Vulnerability Scanning**: Integrate automated vulnerability scanning (Trivy, OWASP Dependency-Check) into the pipeline.
- **Immutable Container Tags**: Never deploy with the `:latest` tag. Use immutable semantic versions or git commit SHAs.
