# Git Hooks & Multi-Stack Quality Gate Manager (`ws hooks`)

The **Workspace Engine Git Hooks** module provides an automated, deterministic quality gate, security scanner, and policy enforcement system executed locally prior to every `git push`.

---

## 🎯 Purpose & Benefits

- **Shift-Left Detection**: Catches syntax errors, broken types, formatting violations, and failing tests on the developer machine in $< 5$ seconds before reaching CI.
- **Zero Secrets Leakage**: Instantly blocks pushes containing `.env` files, private keys, API keys, or JWT secrets in diffs.
- **Strict Git Policy Enforcement**: Ensures Conventional Commits in imperative English and **ZERO AI MENTIONS or robot emojis (🤖)**.
- **Agnostic Multi-Stack Detection**: Automatically detects Python, Node/React, Java/Kotlin, Go, Rust, Flutter, and executes corresponding linters and tests with zero manual configuration.

---

## 🛡️ The 4 Quality Gate Stages

During `git push`, the pre-push hook sequentially executes 4 stages:

```
[Quality Gate Pre-Push Hook] Verifying code quality and security before push...
🔒 [1/4] Scanning secrets and forbidden tracked files...
✔ Security & Secrets: PASS
📝 [2/4] Verifying commit policies & Zero AI mentions...
✔ Git Policies & Zero AI Mentions: PASS
🔍 [3/4] Running multi-stack static linters...
✔ Linters & Static Analysis: PASS
🧪 [4/4] Running automated test suites...
✔ Test Suites: PASS
🚀 All checks passed. Proceeding with git push...
```

---

## 💻 CLI Usage (`ws hooks`)

### 1. Check Hooks Status
```bash
ws hooks status
```

### 2. Install Hook in Local Repository
```bash
ws hooks install
```

### 3. Install Hook Globally (Entire Machine)
```bash
ws hooks install --global
```

### 4. Uninstall Hooks
```bash
ws hooks uninstall
ws hooks uninstall --global
```
