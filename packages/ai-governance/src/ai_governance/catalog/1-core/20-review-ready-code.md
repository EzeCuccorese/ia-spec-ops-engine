# Review-Ready Code

## Invariants
- **Types & API**: Optional only when callers omit; validate upstream shapes before indexing; reject non-finite/overflowing numbers before range checks; explicit ops over sentinels; plural REST paths.
- **Errors & Timeouts**: Map timeouts/connection errors to status errors; degrade optional reads, fail guards closed; distinguish unread data from empty; translate library errors preserving cause/status; report saved vs failed steps on partial writes, keeping the original error if cleanup fails.
- **Security & Regex**: Omit bodies/secrets (incl. nested) from logs & spans (`06`); avoid backtracking regexes on untrusted input.
- **Tests & Reuse**: Assert error codes/diagnostics, not just exception types (`04`); name parametrized cases; fetch only used data; apply `09`, `11`, `12`.
- **PR Hygiene**: Drop temp/debug code; update docs with code; configure target envs (note disabled prod), no env values in code; justify new file types; apply `17`, `18`, `19`.
