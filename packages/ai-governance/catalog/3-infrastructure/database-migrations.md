# Database Migrations & Safety

## Absolute Invariants
- **MongoDB Backup Mandate**: Before executing any mutation (update/delete/drop), export a JSON collection backup named `<cluster>_<database>_<collection>_<YYYYMMDD_HHMMSS>.json`.
- **Versioned Schema Migrations**: Use Flyway, Liquibase, or Mongock. Prohibit `ddl-auto: update` in production.
- **Idempotency**: Every migration must be safely re-runnable ($ times) without failures or duplicate records.
- **Business Keys**: Never hardcode MongoDB ObjectIds across environments; use domain business keys.
