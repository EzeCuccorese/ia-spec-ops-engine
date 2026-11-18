# Database Migrations & Safety

## Absolute Invariants
- **MongoDB Backup Mandate**: Before executing any manual data mutation (`update`, `delete`, or `drop`), export a JSON collection backup named `<cluster>_<database>_<collection>_<YYYYMMDD_HHMMSS>.json`.
- **Versioned Schema Migrations**: Manage schema changes through Flyway, Liquibase, or Mongock. Never use `ddl-auto: update` in production.
- **Idempotency**: Design every migration to be re-runnable multiple times safely (using guards such as `IF NOT EXISTS`, `IF EXISTS`, or idempotent upserts) without failing or creating duplicate records.
- **Business Keys**: Never hardcode database-generated IDs (such as MongoDB `ObjectId`s) across environments; match records by stable domain business keys instead.
- **Out-of-Order Versions**: A migration whose version is lower than the latest applied version may be skipped silently by the runner; check version ordering before deploying and bump the version if needed.
