# Review-Ready Code

## Invariants
- **Types & API**: Mark parameters or fields optional only when supported callers legitimately omit them. Validate upstream shapes before indexing. Reject `NaN`, `Infinity`, and overflowing numbers before range checks. Prefer explicit operations over sentinel values that alter API meaning. Use plural nouns for REST paths.
- **Errors & Timeouts**: Map timeouts and connection failures to domain status errors. Degrade optional reads without breaking the main flow, and fail permission/security guards closed. Distinguish unread data from a valid empty result. Translate library errors while keeping cause and status. On partial multi-step writes, report succeeded vs. failed steps, keeping the original error if cleanup fails.
- **Security & Regex**: Exclude request bodies and secrets (including nested fields) from logs and trace spans. Avoid regexes with overlapping alternatives or nested repetition on untrusted input.
- **Tests & Reuse**: Assert contractual error codes or stable diagnostics rather than bare exception types. Name every parametrized test case descriptively. Fetch only data the active path consumes.
- **PR Hygiene**: Remove temporary overrides and debug code before review. Update affected docs and examples in the same PR. Configure every target environment (noting disabled production) with env values out of code. Explain any new file type in the PR description.
