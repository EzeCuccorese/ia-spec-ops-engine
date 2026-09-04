# Security (OWASP Top 10) & Privacy

## Invariants
- **Zero Hardcoded Secrets**: Prohibit API keys, database passwords, tokens, or private certificates in versioned code. Inject exclusively via secure environment variables or secret managers.
- **Zero PII in Logs**: Never log Personally Identifiable Information (PII: full names, emails, national IDs, credit cards, bank accounts, passwords, or session tokens).
- **Border Validation & Sanitization**: Validate and sanitize all external inputs at the system boundary against SQL/NoSQL injection, XSS, Path Traversal, and SSRF.
- **Least Privilege & Safe Headers**: Enforce strict security headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `HSTS`) and least-privilege IAM roles.
