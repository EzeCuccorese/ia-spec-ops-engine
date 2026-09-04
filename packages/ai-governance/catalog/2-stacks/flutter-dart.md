# Flutter & Dart Standards

## Invariants
- **State Management**: Use declarative, decoupled state management (Riverpod or BLoC). Isolate UI widgets from business logic.
- **Widget Invariants**: Declare stateless widgets with `const` constructors to prevent unnecessary rebuilds.
- **Resource Cleanup**: Always call `dispose()` on `TextEditingController`, `AnimationController`, and stream subscriptions to prevent memory leaks.
- **Responsive Layout**: Build adaptive layouts using `LayoutBuilder` and responsive breakpoints.
