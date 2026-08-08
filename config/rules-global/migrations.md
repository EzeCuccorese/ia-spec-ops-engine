# Data Migrations — Mongock (Java / Spring Boot)

## Fundamental Principle

Data migrations completely replace **any manual query execution** for parametric data (system configurations, business rules). If a change previously required running a manual script, **it is now a versioned migration**. Manual database queries in production or staging for parametric data are strictly prohibited.

Migrations manage **strictly** configuration data and business rules. They must **never** touch operational data (such as orders, financial transactions, user accounts, or audit logs).

---

## `@ChangeUnit` Class Structure (Mongock 5)

Every `@ChangeUnit` implementation must contain:
1. **`@Execution`** — Main execution logic, fully idempotent.
2. **`@RollbackExecution`** — Rollback logic reverting exact changes made by execution (must never be left empty).
3. **Precondition Check** — Validates required database state prior to applying changes.
4. **Idempotency** — Ensures the migration can run $N$ times safely without throwing errors or duplicating entries.

```java
@Slf4j
@ChangeUnit(id = "NNN-description-kebab-case", order = "NNN", author = "ms-service-name")
public class O00N_NNN_DescriptionCamelCase {

    private final MongoTemplate mongoTemplate;

    public O00N_NNN_DescriptionCamelCase(final MongoTemplate mongoTemplate) {
        this.mongoTemplate = mongoTemplate;
    }

    @Execution
    public void execution() {
        // 1. Precondition check
        if (!mongoTemplate.collectionExists("my_collection")) {
            log.warn("Precondition failed: collection does not exist, skipping");
            return;
        }
        // 2. Idempotency check
        final Query existsQuery = new Query(Criteria.where("business_key").is("my-key"));
        if (mongoTemplate.exists(existsQuery, "my_collection")) {
            log.info("Document already exists, skipping");
            return;
        }
        // 3. Execution logic
        final Document doc = loadFromJson("migrations/data/my-document.json");
        mongoTemplate.getCollection("my_collection").insertOne(doc);
    }

    @RollbackExecution
    public void rollback() {
        final Query q = new Query(Criteria.where("business_key").is("my-key"));
        mongoTemplate.remove(q, "my_collection");
    }

    private Document loadFromJson(final String resourcePath) {
        try (final InputStream is = getClass().getClassLoader().getResourceAsStream(resourcePath)) {
            return Document.parse(new String(Objects.requireNonNull(is).readAllBytes()));
        } catch (IOException e) {
            throw new IllegalStateException("Cannot load migration data: " + resourcePath, e);
        }
    }
}
```

---

## Business Keys vs Hardcoded ObjectIds

Reference entities across microservices using **business keys** (e.g., UUIDs, domain codes), never hardcoded MongoDB `ObjectId` strings.

---

## External JSON Data Payloads

Document payloads must be saved in `src/main/resources/migrations/data/<name>.json`, rather than being built inline inside Java code.
