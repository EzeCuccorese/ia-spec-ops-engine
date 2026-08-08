# Global Development Rules (Agnostic)

This directory contains the core specifications and global development rules that apply to all environments, tools, and projects within the toolkit.

## Global Rules Index

* [interaction.md](interaction.md): Communication style, chat response formatting, bounded editing scope, and mandatory verification.
* [git_workflow.md](git_workflow.md): Git conventions, Conventional Commits, pre-push test execution, and branch rules.
* [coding_practices.md](coding_practices.md): Standards for Java/Spring Boot, Node.js/TypeScript, Python/FastAPI, React/JSX, and software architecture.
* [databases.md](databases.md): Access policies for MongoDB and PostgreSQL, including pre-write JSON backups and strict approval.
* [migrations.md](migrations.md): Idempotency rules, preconditions, and structure for parametric data migrations with Mongock.
* [observability.md](observability.md): Structured logging, MDC fields, correlation using `X-Request-Id` / `X-Trace-Id`, and metrics.
* [security.md](security.md): Secret protection, system edge input validation, OWASP Top 10, and dependency vulnerability scanning.
