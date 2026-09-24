# Modern PHP 8.2+ Standards

## Invariants
- **Strict Types**: Include `declare(strict_types=1);` as the first statement in every PHP file.
- **Readonly Classes & Promotion**: Use `readonly class` and Constructor Property Promotion for DTOs and Value Objects.
- **Type Safety**: Provide explicit return types and parameter types. Prohibit `mixed` unless strictly generic.
- **Testing**: Pest or PHPUnit for unit and feature tests.
