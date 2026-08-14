---
name: sdd-exec
description: "Fase 7 de SDD: Ejecuta iterativamente las tareas de tasks.md utilizando roles de Agente Worker y Agente QA Reviewer."
argument-hint: "<nombre-del-feature o ruta a tasks.md>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Exec — Fase 7: Orquestación Iterativa de Tareas y Protocolo de Arnés

Paso 7 del ciclo de vida de **Spec-Driven Development (SDD)**. Orquesta la ejecución de tareas mediante el **Arnés de Ejecución Multi-Agente** para mantener la eficiencia del contexto de ventana, controles de calidad estrictos e historial persistente de ejecución.

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Worker Implementation Agent** y al **QA Code Reviewer Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Worker Implementation Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (QA Code Reviewer Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## ⚡ Protocolo Híbrido para Habilidades de Agentes (Determinismo + Validación Dinámica de IA)
Al ejecutar esta habilidad, el agente DEBE cumplir 3 fases:
1. **Fase 1 (Determinística)**: Ejecutar herramientas CLI / scripts estáticos (`sdd ...`).
2. **Fase 2 (Auditoría Dinámica de IA)**: Inspeccionar el código fuente del repositorio.
3. **Fase 3 (Enriquecimiento Explícito)**: Inyectar las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md`.

---

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-exec <parámetros>`).

## 👥 Roles Multi-Agente

1. 👑 **Agente Líder / Orquestador**:
   - Analiza `tasks.md` mediante `sdd harness next`.
   - Extrae la carga de contexto mínima y enfocado para la tarea activa (evita la saturación del contexto).
   - Lanza el Agente Worker (`invoke_subagent` o ejecución directa) y el Agente QA Reviewer.
   - Administra el ciclo de auto-corrección (Máximo 3 reintentos).


2. 🛠️ **Agente Worker**:
   - **Contratos Primero**: Define interfaces y tipos antes de la lógica de negocio.
   - **Harnés de Pruebas**: Escribe o actualiza la suite de pruebas antes de implementar la lógica.
   - **Implementación Mínima**: Implementa solo el código estrictamente necesario (YAGNI).
   - **Historial Persistente**: Registra el resumen de ejecución en `.specify/history/<timestamp>-<task_id>-worker.md` mediante `python3 -m devscripts.cli.sdd harness log-worker`.
   - **Cero Atribución de IA**: NUNCA escribir `// Generado con IA` ni emojis 🤖.

3. 🔍 **Agente QA Reviewer**:
   - Audita la solución según la **Verificación Estricta de SDD**:
     - Linter: `npm run lint` / `oxlint` / `pytest` / `./gradlew check`.
     - Pruebas unitarias/integración aprobadas.
     - **Lectura de Confirmación Tras Mutación**: Verifica la consulta GET o lectura en BD después de escribir.
     - Cero secretos hardcodeados y cero PII registrada en logs.
     - Auditoría de lista contra `.specify/specs/<feature>/checklist.md`.
   - **Historial Persistente**: Registra el resultado de la validación en `.specify/history/<timestamp>-<task_id>-qa.md` mediante `python3 -m devscripts.cli.sdd harness log-qa`.
   - **Remediación Sintética**: Si es rechazado (`FAIL`), proporciona un resumen de error de alto nivel y pasos de remediación (sin volcar logs crudos al contexto).

---

## 📋 Flujo de Ejecución del Arnés

1. **Localizar Feature Activo y Estado**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   python3 -m devscripts.cli.sdd harness status
   ```

2. **Obtener Siguiente Tarea**:
   ```bash
   python3 -m devscripts.cli.sdd harness next
   ```

3. **Fase 1: Ejecución del Worker**:
   - Implementar el cambio con contexto acotado.
   - Registrar la ejecución:
     ```bash
     python3 -m devscripts.cli.sdd harness log-worker --task-id "<TASK_ID>" --summary "<RESUMEN>" --details "<DETALLES>"
     ```

4. **Fase 2: Verificación del QA Reviewer**:
   - Ejecutar linter y pruebas.
   - Realizar lectura de confirmación tras mutación.
   - Registrar resultado de QA:
     ```bash
     python3 -m devscripts.cli.sdd harness log-qa --task-id "<TASK_ID>" --summary "<RESUMEN>" --details "<DETALLES>" --passed
     ```

5. **Auto-Corrección y Actualización de Estado**:
   - Si QA aprueba (`--passed`), `tasks.md` se actualiza automáticamente a `- [x]`.
   - Si QA falla (máximo 3 reintentos), ejecutar iteración de remediación con el Agente Worker usando retroalimentación sintética.

6. **Avanzar a Convergencia (`/sdd-converge`)** cuando todas las tareas en `tasks.md` estén marcadas como `[x]`.

7. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia de continuidad:
     - Si quedan tareas pendientes: `python3 -m devscripts.cli.sdd harness next` (o continuar con la siguiente tarea).
     - Si todas las tareas están completadas (`[x]`):
       ```markdown
       ### 🎯 Próximos Pasos Recomendados

       Todas las tareas de desarrollo han sido ejecutadas y verificadas por QA.
       1. Ejecutar `/sdd-converge` para realizar la verificación final de criterios Gherkin y checklist de calidad.
       ```
