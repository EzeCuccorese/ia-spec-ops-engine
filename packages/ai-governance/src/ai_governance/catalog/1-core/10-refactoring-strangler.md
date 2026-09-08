# Refactoring & Legacy Modernization

## Invariants
- **Boy Scout Rule**: Always leave code cleaner than you found it, strictly within the scope of the current task. Never perform unrelated mass refactors.
- **Strangler Fig Pattern**: Incrementally intercept and replace legacy endpoints or services with new modular implementations without risky Big Bang rewrites.
- **Anti-Corruption Layer (ACL)**: Isolate new domain models from legacy data structures by translating through an explicit ACL adapter layer.
- **Safety Nets**: Ensure full test harness coverage before modifying existing legacy behavior.
