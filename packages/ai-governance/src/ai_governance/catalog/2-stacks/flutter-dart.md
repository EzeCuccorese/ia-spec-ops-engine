# Flutter & Dart Standards

## Invariants
- **State Management**: Use declarative, decoupled state management (Riverpod or BLoC). Isolate UI widgets from business logic.
- **Widget Invariants**: Declare stateless widgets with `const` constructors to prevent unnecessary rebuilds.
- **Resource Cleanup**: Always call `dispose()` on `TextEditingController`, `AnimationController`, and stream subscriptions to prevent memory leaks.
- **Responsive Layout**: Build adaptive layouts using `LayoutBuilder` and responsive breakpoints.
- **Typed Models**: Enable `strict-casts`, `strict-inference` and `strict-raw-types` in `analysis_options.yaml`; no `dynamic` beyond the JSON decode line, map it into `json_serializable`/`freezed` models.
- **Boundary Validation**: Parse URLs with `Uri.tryParse` (check scheme and host) and share one validator per format across forms; never duplicate regex per field.
