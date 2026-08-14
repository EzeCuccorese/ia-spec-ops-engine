---
name: sdd-clarify
description: "Fase 2 de SDD: Identifica y resuelve ambigüedades, supuestos y casos borde en spec.md (clarify.md)."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Clarify — Fase 2: Auditoría de Ambigüedades y Calidad

Paso 2 del ciclo de vida de **Spec-Driven Development (SDD)**. Audita `spec.md` para garantizar cero requerimientos ambiguos o subespecificados antes del diseño técnico:

```
.specify/specs/<nombre-del-feature>/clarify.md
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Ambiguity Resolution Specialist** y al **Risk Audit QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Ambiguity Resolution Specialist)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Risk Audit QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-clarify <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   FEATURE_NAME="$(python3 -m devscripts.cli.sdd feature)"
   FEATURE_DIR="$REPO_ROOT/.specify/specs/$FEATURE_NAME"
   ```

2. **Auditar `spec.md`**:
   - Leer `$FEATURE_DIR/spec.md`.
   - Identificar supuestos implícitos, casos borde en límites, contratos de datos faltantes o conflictos de rendimiento.

3. **Entrevista de Aclaración / Preguntas**:
   - Formular preguntas claras al desarrollador humano si persisten decisiones de diseño o trade-offs abiertos.

4. **Generar `clarify.md`**:
   - Documentar cada pregunta con su decisión explícita.
   - Actualizar el estado de la fase activa:
     ```bash
     python3 -m devscripts.cli.sdd phase clarify
     ```

5. **Punto de Control Humano**:
   - Presentar `clarify.md` al usuario para su confirmación antes de avanzar a la Fase 3 (`/sdd-plan`).

6. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para diseñar la solución técnica y contratos formales de datos:
1. Ejecutar `/sdd-plan` para crear el blueprint técnico y esquemas de datos (`plan.md`).
```
