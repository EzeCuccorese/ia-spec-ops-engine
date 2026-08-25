# Technical Debt, Bugs & Anti-Patterns Catalog (`tech-debt.md`)

**Repository**: `{repo_name}`  
**Date**: {date}  
**Overall Status**: 🟢 HEALTHY / 🟡 NEEDS ATTENTION / 🔴 HIGH RISK

---

## 🎯 1. Executive Summary
{executive_summary}

---

## 📈 2. Impact & Priority Matrix
- 🔴 **CRITICAL**: Security vulnerabilities, exposed credentials, data loss risks.
- 🟠 **HIGH**: Business logic without tests, N+1 queries, unvalidated HTTP boundaries.
- 🟡 **MEDIUM**: God classes, duplicated code, unparameterized logging.
- 🟢 **LOW**: Deprecated comments, minor format inconsistencies.

---

## 📑 3. Findings & Action Plans

### 🔴 Critical Findings
#### `[TD-001]` {Finding Title}
- **Category**: Security / Persistence / SDD / Quality
- **Location**: [`{file_path}:L{line}`]({file_path}#L{line})
- **Description**: {Detailed explanation of risk}
- **Remediation Plan**:
  1. Step 1: {Concrete technical action}
  2. Step 2: {Verification test}
- **Quick Remediation Command**:
  ```bash
  /sdd-quick "Fix [TD-001]: <summary> in <file_path>"
  ```
