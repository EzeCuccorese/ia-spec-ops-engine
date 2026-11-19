# Review-Ready Code

## Invariants
- **Types & API**: Mark params/fields optional only when callers legitimately omit them. Validate upstream shapes before indexing. Reject `NaN`, `Infinity`, and overflows before range checks. Prefer explicit ops over meaning-altering sentinels. Use plural REST paths. Send currency/units explicitly (ISO codes), never derived from locale or language.
- **Errors & Timeouts**: Map timeouts/connection failures to domain status errors. Degrade optional reads without breaking the main flow; fail permission/security guards closed. Distinguish unread data from empty results. Translate library errors keeping cause and status. On partial multi-step writes, report succeeded vs. failed steps, keeping the original error if cleanup fails. Enforce create-if-absent across services via conditional write in the owner service (409 on conflict), never caller-side GET then POST.
- **Security & Regex**: Exclude request bodies and secrets (including nested fields) from logs and spans. Avoid regexes with overlapping alternatives or nested repetition on untrusted input.
- **Tests & Reuse**: Assert error codes or stable diagnostics, not bare exception types. Name parametrized cases descriptively. Fetch only data the active path uses.
- **PR Hygiene**: Strip temp overrides and debug code before review. Update affected docs/examples in the same PR. Configure all target envs (noting disabled prod) via external env config. Explain new file types in the PR description.
