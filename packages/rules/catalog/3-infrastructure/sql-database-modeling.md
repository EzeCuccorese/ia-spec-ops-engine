# SQL Modeling & Query Performance

## Invariants
- **Indexing Strategy**: Create B-Tree indexes on foreign keys and frequently queried filter columns. Use composite indexes ordered by cardinality.
- **Anti-N+1 Mandate**: Prohibit N+1 queries. Use explicit `JOIN FETCH` or batch fetching.
- **Execution Plans**: Run `EXPLAIN ANALYZE` on complex queries before deploying to production.
- **ACID Transactions**: Keep database transactions short and tightly scoped to prevent connection pool starvation.
