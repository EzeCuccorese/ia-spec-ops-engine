## 👥 Specialized Multi-Agent Roles (SpecOps Architecture)

1. 👑 **Lead Orchestrator Agent**:
   - Manages feature state in `.specify/feature.json`, bounds execution context, and coordinates phase execution.
   - Invokes domain subagents using `invoke_subagent`.
   - Governs autonomous self-healing loops (maximum 3 retries before escalating to human engineer).

2. 🛠️ **Phase Specialist Agent (Worker / Domain Agent)**:
   - Implements the technical or specification task focused 100% on its domain expertise.
   - Applies the 4 SDD Pillars (Contracts First, Test-First, Minimal Implementation, Early Detection).

3. 🔍 **Quality Validation Agent (QA Reviewer / Auditor Agent)**:
   - Adversarially audits deliverables and source code (linters, test suites, contracts, PII, checklist).
   - Approves (`PASS`) or rejects (`FAIL`) with actionable remediation feedback.
