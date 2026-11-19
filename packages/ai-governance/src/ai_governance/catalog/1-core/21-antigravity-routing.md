# Antigravity Model Routing

## Invariants
- Keep the main conversation available while long tasks run in the background. Use `swarm` to select a model and effort for each task.
- Small fixes, tests, and documentation: `gemini-4-hydrogen-low` or `gemini-4-hydrogen-medium`.
- Standard implementation: `gemini-4-hydrogen-medium` or `gemini-4-neon-medium`.
- Complex design or difficult debugging: `gemini-4-neon-high`. Use `xhigh` only when the user explicitly asks.
- Use a quick scout for a narrow lookup instead of starting a swarm.
