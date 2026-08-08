# 🚀 Guía y Registro de Migraciones de Base de Datos

**Proyecto**: Devscripts / Enterprise Platform  
**Última Actualización**: 2026-08-07  
**Estado**: 🟢 ACTIVO  

---

## 📑 Tabla de Contenidos

- [Visión General](#-visión-general)
- [Reglas Obligatorias para Migraciones](#-reglas-obligatorias-para-migraciones)
- [Historial y Registro de Migraciones](#-historial-y-registro-de-migraciones)
- [Estructura Estándar Mongock (`@ChangeUnit`)](#-estructura-estándar-mongock-changeunit)
- [Protocolo de Seguridad y Backup Pre-Ejecución](#-protocolo-de-seguridad-y-backup-pre-ejecución)

---

## 🌐 Visión General

El mantenimiento del esquema y datos en las bases de datos de la plataforma se gestiona exclusivamente mediante migraciones automatizadas y versionadas:
- **MongoDB**: Gestionado con **Mongock** mediante unidades de cambio `@ChangeUnit`.
- **PostgreSQL**: Gestionado con **Flyway** mediante scripts SQL versionados (`V1__...sql`).

Queda totalmente prohibida la ejecución de modificaciones manuales directas en esquemas de producción o staging sin un script de migración asociado.

---

## 📏 Reglas Obligatorias para Migraciones

1. **Idempotencia Garantiada**:
   - Cada migración debe ser capaz de ejecutarse N veces sin fallar, sin duplicar registros ni corromper estados existentes.
   - Usar precondiciones (`if (!collectionExists) ...` o `CREATE TABLE IF NOT EXISTS`).

2. **Rollback Requerido (`@RollbackExecution`)**:
   - Toda migración debe incluir su correspondiente método o script de reversión.
   - En Java Mongock, `@RollbackExecution` **jamás debe dejarse vacío**.

3. **Payloads Externos**:
   - Los datos masivos o documentos JSON complejos no deben definirse inline dentro de clases Java o SQL.
   - Deben guardarse en archivos JSON individuales en `src/main/resources/migrations/data/<migration_id>.json`.

4. **Uso de Claves de Negocio**:
   - Referenciar siempre documentos o registros mediante sus `business keys` (UUIDs / Slugs), nunca mediante `ObjectId` hardcodeados.

---

## 📜 Historial y Registro de Migraciones

| Versión / ID | Fecha | Motor | Descripción | Idempotente | Rollback Disponible |
| :--- | :---: | :---: | :--- | :---: | :---: |
| `V1.0.0__init_schema` | 2026-08-01 | PostgreSQL | Creación de tablas base `workspaces` y `repositories`. | SI | SI (`U1.0.0__init_schema.sql`) |
| `mongock-001-init-collections` | 2026-08-02 | MongoDB | Inicialización de colecciones `workspaces` y `audit_events` con índices. | SI | SI (`@RollbackExecution`) |
| `mongock-002-add-audit-index` | 2026-08-05 | MongoDB | Creación de índice compuesto en `audit_events` (`workspace_id`, `timestamp`). | SI | SI |

---

## ☕ Estructura Estándar Mongock (`@ChangeUnit`)

A continuación se presenta el patrón de referencia para migraciones en MongoDB con Java y Mongock:

```java
package com.devscripts.migrations;

import io.mongock.api.annotations.ChangeUnit;
import io.mongock.api.annotations.Execution;
import io.mongock.api.annotations.RollbackExecution;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.index.Index;
import org.springframework.data.mongodb.core.domain.Sort;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@ChangeUnit(id = "mongock-002-add-audit-index", order = "002", author = "devscripts-team")
public class ChangeUnit002AddAuditIndex {

    private static final String COLLECTION_NAME = "audit_events";

    @Execution
    public final void execution(final MongoTemplate mongoTemplate) {
        log.info("Ejecutando migración: mongock-002-add-audit-index");
        
        if (!mongoTemplate.collectionExists(COLLECTION_NAME)) {
            mongoTemplate.createCollection(COLLECTION_NAME);
            log.info("Colección {} creada con éxito", COLLECTION_NAME);
        }

        mongoTemplate.indexOps(COLLECTION_NAME).ensureIndex(
            new Index()
                .on("workspace_id", Sort.Direction.ASC)
                .on("timestamp", Sort.Direction.DESC)
                .named("idx_audit_ws_ts")
        );
        log.info("Índice idx_audit_ws_ts asegurado correctamente.");
    }

    @RollbackExecution
    public final void rollbackExecution(final MongoTemplate mongoTemplate) {
        log.info("Revirtiendo migración: mongock-002-add-audit-index");
        
        if (mongoTemplate.collectionExists(COLLECTION_NAME)) {
            mongoTemplate.indexOps(COLLECTION_NAME).dropIndex("idx_audit_ws_ts");
            log.info("Índice idx_audit_ws_ts eliminado durante rollback.");
        }
    }
}
```

---

## 🛡️ Protocolo de Seguridad y Backup Pre-Ejecución

Antes de ejecutar cualquier migración de datos o mutación manual en MongoDB:

1. **Backup JSON Obligatorio**:
   ```bash
   mongoexport --db=devscripts --collection=workspaces --out=workspaces_prod_workspaces_20260807_162300.json --jsonArray
   ```
2. **Formato del Nombre**: `<cluster>_<database>_<collection>_<YYYYMMDD_HHMMSS>.json`.
3. **Confirmación Literal**: Solicitar al usuario confirmación y validar que la respuesta sea **exactamente "OK WRITE"**.
