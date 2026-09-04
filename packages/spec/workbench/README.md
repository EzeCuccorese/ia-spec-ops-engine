# SDD Agent Workbench: Java Payment Orders API Demo

Isolated, interactive test environment for executing the complete **Spec-Driven Development (SDD)** lifecycle using AI coding agents (Google Gemini) on a real-world **Java 21 / Spring Boot** application.

---

## Toolkit Structure

```
packages/spec/workbench/
├── .env.example              # Secure environment variables template
├── runner/                   # Python TUI orchestrator and runners
│   ├── sdd_runner_tui.py     # Main interactive runner with Rich TUI
│   ├── clean_workbench.py    # Reset script to leave the environment 100% pristine
│   ├── gemini_client.py      # Connector to Agent Platform (gemini-flash-latest)
│   └── agent_roles.py        # Specialized agent personas (SpecAuthor, Craftsman, Judge)
├── test-sdd/                 # Target Java 21 / Spring Boot project
│   ├── build.gradle          # Gradle build with JUnit 5, AssertJ, and JaCoCo
│   ├── gradlew               # Executable Gradle wrapper
│   ├── .spec/                # Spec governance (policy.json, verification.json)
│   └── src/                  # Java source code generated under strict TDD
```

---

## How to Run

1. **Environment Configuration**:
   Copy `.env.example` to `.env` in this directory:
   ```bash
   cp packages/spec/workbench/.env.example packages/spec/workbench/.env
   ```
   Edit `.env` and set your `GEMINI_API_KEY` (obtained from [Google AI Studio](https://aistudio.google.com/)).

2. **Run Interactive Console Runner**:
   ```bash
   python3 packages/spec/workbench/runner/sdd_runner_tui.py
   ```

3. **Human-in-the-Loop Workflow**:
   * **Phase 1 (Spec)**: The agent authors `spec.md` with Gherkin acceptance scenarios `@s1`, `@s2`, `@s3`. The TUI displays the formatted specification and requests human sign-off.
   * **Phase 2 (Plan)**: The architecture agent produces `plan.md` and `tasks.md` adhering to clean Java idioms (records, immutability, constructor injection).
   * **Phase 3 (TDD)**:
     * Red Cycle: Generates JUnit 5 test and runs `./gradlew test` (fails).
     * Green Cycle: Generates minimal Java implementation and runs `./gradlew test` (passes 100%).
     * Writes development log to `work.md` on disk.
   * **Phase 4 (Verification & Craftsmanship Judge)**:
     * Runs `spec verify` auditing traceability across all `@s` scenarios.
     * **The Judge** agent audits code against YAGNI / over-engineering and issues the `APPROVED` verdict.
   * **Phase 5 (Seal & Clean)**: The runner prompts for final confirmation and executes `spec finish`. Upon completion, it offers to automatically clean the workspace.

4. **Reset Environment at Any Time**:
   To reset the target demo project to a 100% pristine baseline:
   ```bash
   python3 packages/spec/workbench/runner/clean_workbench.py
   # Or without interactive confirmation prompt:
   python3 packages/spec/workbench/runner/clean_workbench.py --force
   ```

