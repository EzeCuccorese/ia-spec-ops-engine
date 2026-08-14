---
name: sdd-doc
description: "Motor autónomo de documentación: escanea el proyecto, genera un plan interactivo de actualización de docs/READMEs respetando el principio DRY (Fuente Única de Verdad), solicita confirmación al usuario y ejecuta los cambios."
argument-hint: "[--full] [--scope <modulo>] [--fix]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Doc — Motor Autónomo de Documentación y Guías Técnicas

Estás ejecutando la habilidad **SDD Documentation Engine**. Esta habilidad escanea la base de código, purga referencias obsoletas o contaminadas, consolida la documentación bajo `docs/` y actualiza guías técnicas y `README.md` siguiendo estrictamente el principio **DRY (Don't Repeat Yourself / Fuente Única de Verdad)** mediante un flujo interactivo de **Plan ➔ Aprobación ➔ Ejecución**.

---

## 🏛️ Directiva Obligatoria DRY (Fuente Única de Verdad)

- **Cero Duplicación de Contenido**: Prohibido duplicar tablas de comandos, referencias de API o guías operativas entre los `README.md` de los subproyectos y los índices generales.
- **Enlaces Relativos**: Si una información técnica pertenece a un subproyecto (ej: `packages/workspace/` o `packages/sdd/`), la documentación canónica DEBE residir en el README de dicho subproyecto. Los índices en `docs/` deben enlazar a estos archivos mediante enlaces markdown relativos.
- **Consolidación Estructurada**: Los documentos conceptuales transversales residen en `docs/architecture/` y `docs/sdd/`.

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Coordina el flujo de análisis, redacción del plan y confirmación del usuario.
   - Invoca al **Especialista en Documentación Técnica** y al **Validador QA de Documentación**.
2. 🛠️ **Agente Especialista (Documentation Engine Specialist)**:
   - Inspecciona los cambios recientes en código, puntos de entrada y contratos de API.
   - Diseña el plan de actualización y redacta las guías en español claro y conciso.
3. 🔍 **Agente Validador QA (Documentation QA Reviewer)**:
   - Verifica que no haya enlaces rotos, que se respete el principio DRY y que no se hayan filtrado secretos ni PII.

---

## ⚡ Protocolo Híbrido para Habilidades de Agentes (Determinismo + Validación Dinámica de IA)
Al ejecutar esta habilidad, el agente DEBE cumplir 3 fases:
1. **Fase 1 (Determinística)**: Ejecutar herramientas CLI / scripts estáticos (`sdd ...`).
2. **Fase 2 (Auditoría Dinámica de IA)**: Inspeccionar el código fuente del repositorio.
3. **Fase 3 (Enriquecimiento Explícito)**: Inyectar las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md`.

---

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetros**: Validar el alcance (`--scope`, `--full`, `--fix`) y asegurar que el repositorio esté en un estado limpio.


---

## 📋 Flujo de Ejecución en 4 Fases

### Fase 1: Escaneo y Detección de Cambios
1. Identificar la raíz del proyecto y el alcance (`--scope` o cambios recientes en git).
2. Escanear contratos de entrada/salida, scripts ejecutables, variables `.env.example` y estructuras de paquetes.
3. Detectar inconsistencias, enlaces caídos o documentación desactualizada.

### Fase 2: Elaboración del Plan de Documentación
El agente DEBE formular un **Plan de Actualización de Documentación** detallando:
- Archivos a modificar o crear (ej: `docs/README.md`, `packages/workspace/README.md`).
- Secciones nuevas o modificadas.
- Enlaces relativos a verificar.

### Fase 3: Confirmación Interactiva del Usuario (Punto de Control)
- Presentar el plan al usuario de forma estructurada.
- **DETENERSE Y ESPERAR** la confirmación explícita del usuario antes de modificar cualquier archivo de documentación.

### Fase 4: Ejecución y Validación Final
- Tras la aprobación del usuario, aplicar los cambios de forma idempotente y limpia.
- Validar que todos los enlaces markdown apunten a archivos existentes.
- Reportar un resumen de archivos actualizados.
