# Project Technical Constitution (`constitution.md`)

**Project**: {project_name}  
**Last Updated**: {date}

---

## 🏛️ 1. Architectural Invariants
1. **Separation of Concerns**: Strict boundary separation between API transport, domain business logic, and infrastructure persistence layers.
2. **Immutability First**: Data transfer objects and domain events must be immutable (`record` in Java, `frozen=True` in Python, `readonly` in TypeScript).
3. **Constructor Dependency Injection**: No direct field injection (`@Autowired` or global state).

---

## 🛡️ 2. Quality & Security Guardrails
- **Conventional Commits**: `type(scope): description` in English, lowercase, imperative mood.
- **ZERO AI MENTIONS**: Strictly no AI mentions or robot emojis in PRs, commits, or comments.
- **Hermetic Testing**: Tests must never depend on external network state without mocking.
- **Input Edge Defense**: Validate every external HTTP or message payload with formal schemas before processing.

---

## 🔍 3. Dynamic IA Discoveries & Project-Specific Conventions
*(This section is automatically updated by `sdd-init` / `sdd-constitution` based on AST analysis of the repository)*
- **Runtime Stack**: {runtime_stack}
- **Build Tools**: {build_tools}
- **Test Frameworks**: {test_frameworks}
- **Conventions**: {discovered_conventions}
