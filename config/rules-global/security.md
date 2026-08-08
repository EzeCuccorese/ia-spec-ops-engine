# Security — OWASP, Fintech, and Best Practices

## Absolute Security Rules

### Secret Protection

- Passwords, API keys, tokens, database connection strings
- Security certificates, private keys
- Database credentials, cloud access keys, CI/CD pipeline secrets

Always use environment variables or dedicated secret management systems. Never hardcode secrets in code or version-controlled configuration files.

### Privacy (Never Log PII or Financial Data)

- Personally Identifiable Information (PII): Full names, national identification numbers, email addresses, phone numbers
- Financial Data: Bank account numbers (IBAN/CBU), credit card numbers, CVV codes, PINs, balances
- Credentials and Tokens: Plaintext passwords, authentication tokens, API keys

---

## Input Validation

- Always validate inputs at system entry boundaries (Spring Boot Bean Validation, Zod in Node.js/TypeScript).
- In Node.js/TypeScript, validate environment variables (`process.env`) with Zod schemas at application startup.

---

## OWASP Top 10 — Mitigations

- Escape and sanitize all inputs to prevent SQL and NoSQL injections.
- Run automated dependency security scans (OWASP Dependency Check in Gradle) to detect and mitigate known vulnerabilities.
- Configure security HTTP headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`).
