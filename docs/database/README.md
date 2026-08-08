# 🗄️ Database Catalog and Structure

This directory serves as the single source of truth for database design, schema catalogs, data dictionaries, and migration/backup policies across project services.

---

## 📂 Module Contents

| File | Description |
| :--- | :--- |
| [`schema.md`](file://~/projects/devscripts/docs/database/schema.md) | Catalog of collections, tables, fields, data types, indexes, and entity relationships (ER Diagrams). |
| [`migrations.md`](file://~/projects/devscripts/docs/database/migrations.md) | Log of database migrations (Flyway / Liquibase / Mongock), execution guides, idempotency, and rollback strategies. |

---

## 📏 General Database Principles

1. **Contract-Driven Design**:
   - Every column/field must define an explicit data type, nullability constraints, and business domain description.
   - Use domain business keys (`business keys` such as UUIDs / Slugs) for cross-service or inter-collection references, avoiding hardcoded MongoDB `ObjectId`s or exposed auto-incrementing IDs.

2. **Versioned and Idempotent Migrations**:
   - Strictly avoid using `ddl-auto: update` or manual mutations in persistent environments.
   - All schema alterations must be managed using versioned migration tools (Flyway/Liquibase for relational databases, Mongock for MongoDB).

3. **No AI Attribution or Hardcoded Secrets**:
   - No table, column comment, or migration script should contain AI tool attributions or hardcoded environment credentials/secrets.

---

## 🛡️ Absolute Pre-Mutation Backup Protocol for MongoDB (No Exceptions)

Before executing any data mutation in MongoDB (`update`, `delete`, `insert`, `drop`, `create-index`), the following security protocol must be strictly satisfied:

1. **Backup Export**:
   - Export the affected collection into JSON format prior to execution.
   - File naming format: `<cluster>_<database>_<collection>_<YYYYMMDD_HHMMSS>.json`.

2. **Literal User Write Approval**:
   - Present exact operation details (filter query, update payload, rationale, and export path).
   - Wait for the user to respond **literally with the exact phrase "OK WRITE"**.
   - Proceeding with the write operation without receiving this literal confirmation is strictly forbidden.

---

## 🔄 Migration Strategy with Mongock (Java)

- **`@ChangeUnit` Structure**: Mandatory implementation of `@Execution` and `@RollbackExecution` methods. Rollback methods must never be left empty.
- **Precondition Checks**: Validate collection and document existence prior to performing modifications.
- **External Payloads**: When inserting or updating complex document structures, store payload data in JSON files under `src/main/resources/migrations/data/` rather than embedding raw JSON inline in Java code.
