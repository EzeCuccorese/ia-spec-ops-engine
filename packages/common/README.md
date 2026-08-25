# cucco-common (`packages/common`)

Shared base library providing typing, rich console utilities, deterministic subprocess execution wrappers, frontmatter parsers, and automated multi-stack project detection for **Cucco SpecOps Engine**.

---

## 📦 Modules Overview

### 1. `devscripts_common.frontmatter`
- Centralized YAML frontmatter parser for markdown rules, specification artifacts, and prompt headers.
- Extracts `description`, `globs`, `alwaysApply`, and custom metadata cleanly.

### 2. `devscripts_common.colors`
- High-contrast ANSI / Rich console color helpers (`log_info`, `log_success`, `log_warning`, `log_error`).
- `strip_ansi()` helper for sanitizing terminal outputs in test runners and logging streams.

### 3. `devscripts_common.subprocess`
- Safe deterministic subprocess execution (`run_command_safe`).
- Mandatory execution timeouts to prevent process hangs.
- Isolated Git execution environment (`isolated_git=True`) to prevent contamination from ambient config files.

### 4. `devscripts_common.project`
- Automated detection of project types, build systems, and runtimes:
  - Spring Boot / Java / Kotlin (Maven, Gradle, `pom.xml`, `build.gradle.kts`).
  - Node.js / TypeScript / React (`package.json`, `tsconfig.json`).
  - Python (`pyproject.toml`, `requirements.txt`, `pytest.ini`).
  - Go (`go.mod`), Rust (`Cargo.toml`), Flutter/Dart (`pubspec.yaml`).
