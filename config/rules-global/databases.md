# Databases — MongoDB, PostgreSQL, and Data Access Rules

## MongoDB — Data Access

- Query MongoDB using configured access tools or interfaces.
- If target database or connection is not specified, request explicit confirmation prior to execution.

---

## MongoDB — MANDATORY Pre-Mutation Backup Protocol

### ABSOLUTE RULE — NO EXCEPTIONS

Before executing **any operation that mutates data in MongoDB**, it is **MANDATORY** to export the affected collection as a JSON backup file first.

This applies strictly to: `update-many`, `update-one`, `$set`, `$rename`, `$unset`, `delete-many`, `delete-one`, `insert-many`, `insert-one`, `drop-collection`, `drop-database`, `create-index`, `drop-index`, and any custom script executing write operations against MongoDB.

### Standard Operating Procedure

1. **Export Collection**: Export the affected collection in JSON format before proceeding with any mutation.
2. **Backup Naming Convention**: Save the backup file using the format: `<cluster>_<database>_<collection>_<YYYYMMDD_HHMMSS>.json`.
3. **Present Operation Details**: Present the exact mutation operation details to the user: target DB, collection, filter, and operation payload.
4. **Require Literal User Approval**: Wait for the user to respond **literally with the exact phrase "OK WRITE"**. No other response constitutes valid authorization.
5. **Execute Mutation**: Execute the write operation only after receiving the literal approval phrase.

If the export step fails: abort execution immediately and notify the user. Never proceed without confirmed backup output.

### Never Mutate Without Explicit User Request

Never execute write operations in MongoDB unless explicitly requested by the user in the current message context. Approval given in a previous conversation context does not carry over.

---

## PostgreSQL

- Avoid using Hibernate `ddl-auto: update` in services running against production data — high risk of schema drift between environments.
- Use versioned schema migration tools (Flyway or Liquibase) for all new microservices.
