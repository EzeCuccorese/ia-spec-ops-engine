---
name: sdd-tasks
description: "Fase 5 de SDD: Desglosa el plan técnico en tareas ejecutables ordenadas (tasks.md) cumpliendo con los 4 Pilares de SDD."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Tasks — Fase 5: Desglose de Tareas Ejecutables

Paso 5 del ciclo de vida de **Spec-Driven Development (SDD)**. Genera la lista ordenada de tareas para guiar la implementación:

```
.specify/specs/<nombre-del-feature>/tasks.md
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Lead Tech Planner Agent** y al **Task Atomization QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Lead Tech Planner Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Task Atomization QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-tasks <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   FEATURE_NAME="$(python3 -m devscripts.cli.sdd feature)"
   FEATURE_DIR="$REPO_ROOT/.specify/specs/$FEATURE_NAME"
   ```

2. **Estructurar Tareas en 4 Fases Estrictas**:
   - **Fase 1: Contratos Primero** (Crear esquemas/interfaces antes de la lógica de negocio).
   - **Fase 2: Harnés de Pruebas** (Escribir suite de pruebas en Rojo que falle por razones esperadas del contrato).
   - **Fase 3: Implementación Mínima** (Escribir código mínimo en Verde para pasar las pruebas).
   - **Fase 4: QA y Verificación** (Linter, build, auditoría sin PII, lectura de confirmación tras mutación).

3. **Guardar `tasks.md` y Actualizar Estado**:
   - Escribir `$FEATURE_DIR/tasks.md`.
   - Actualizar estado de la fase:
     ```bash
     python3 -m devscripts.cli.sdd phase tasks
     ```

4. **Punto de Control Humano**:
   - Presentar el desglose de tareas al usuario para su aprobación antes de la Fase 6 (`/sdd-analyze`).

5. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para ejecutar la auditoría de consistencia cruzada entre especificaciones y tareas:
1. Ejecutar `/sdd-analyze` para verificar la alineación estática de contratos y artefactos.
```
