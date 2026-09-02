# Git Hooks & Multi-Stack Quality Gate Manager (`ws hooks`)

The **Workspace Engine Git Hooks** module provides an automated, deterministic quality gate, security scanner, and policy enforcement system executed locally prior to every `git push`.

---

## 🎯 Purpose & Benefits

- **Shift-Left Detection**: Catches syntax errors, broken types, formatting violations, and failing tests on the developer machine in $< 5$ seconds before reaching CI.
- **Zero Secrets Leakage**: Instantly blocks pushes containing `.env` files, private keys, API keys, or JWT secrets in diffs.
- **Strict Git Policy Enforcement**: Ensures Conventional Commits in imperative English and **ZERO AI MENTIONS or robot emojis (🤖)**.
- **Agnostic Multi-Stack Detection**: Automatically detects Python, Node/React, Java/Kotlin, Go, Rust, Flutter, and executes corresponding linters and tests with zero manual configuration.

---

## 🛡️ The 5 Quality Gate Stages

During `git push` or `ws hooks run`, the pre-push hook sequentially executes 5 stages:

```
[Quality Gate Pre-Push Hook] Verificando calidad y seguridad antes de enviar cambios...
🔒 [1/5] Verificando secretos en los commits que se pushean (gitleaks)...
✔ Seguridad y Secretos: PASS
📝 [2/5] Verificando políticas de commit (Conventional Commits, autosquash)...
✔ Políticas Git: PASS
🔍 [3/5] Ejecutando análisis estático y linters (Ruff, ESLint, PHPCS, Go vet, Cargo clippy, Flutter)...
✔ Linters y Análisis Estático: PASS
🧪 [4/5] Ejecutando suites de tests (Pytest, Jest/Vitest, PHPUnit, Maven/Gradle, Go, Rust, Flutter)...
✔ Suites de Tests: PASS
🪝 [5/5] Delegando al hook pre-push del repositorio (Husky u otro)...
✔ Hooks del Repositorio: PASS
🚀 Todo en orden. Procediendo con git push...
```

---

## 💻 CLI Usage (`ws hooks`)

### 1. Check Hooks Status
```bash
ws hooks status
```

### 2. Run Quality Gate On-Demand (Without pushing)
```bash
ws hooks run
ws hooks run --scope changed
ws hooks run --skip gitleaks,commits
```

### 3. Test Hook Execution
```bash
ws hooks test
```

### 4. Install Hook in Local Repository
```bash
ws hooks install
```

### 5. Install Hook Globally (Entire Machine)
```bash
ws hooks install --global
```

### 6. Uninstall Hooks
```bash
ws hooks uninstall
ws hooks uninstall --global
```
