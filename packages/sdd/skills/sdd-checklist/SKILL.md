---
name: sdd-checklist
description: "Fase 4 de SDD: Establece las Quality Gates (checklist.md) y la Definición de Listo (Definition of Done) para la característica."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Checklist — Fase 4: Definición de Quality Gates

Paso 4 del ciclo de vida de **Spec-Driven Development (SDD)**. Establece la lista de verificación de calidad requerida para marcar la característica como completada:

```
.specify/specs/<nombre-del-feature>/checklist.md
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Quality Gate Specialist** y al **DoD Compliance QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Quality Gate Specialist)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (DoD Compliance QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-checklist <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   FEATURE_NAME="$(python3 -m devscripts.cli.sdd feature)"
   FEATURE_DIR="$REPO_ROOT/.specify/specs/$FEATURE_NAME"
   ```

2. **Construir `checklist.md`**:
   - Incluir criterios de Definición de Listo (Definition of Done - DoD).
   - Incluir requerimientos de pruebas (cobertura JaCoCo $\ge$ 90% para lógica crítica).
   - Incluir verificación de **lecturas de confirmación tras mutaciones (petición GET HTTP o consulta a BD)**.
   - Incluir auditoría de seguridad (sin PII en logs, cero secretos hardcodeados, OWASP).
   - Incluir reglas de Git (Conventional Commits, cero menciones de IA o emojis de robot).

3. **Guardar `checklist.md` y Actualizar Estado**:
   - Escribir `$FEATURE_DIR/checklist.md`.
   - Actualizar estado de fase:
     ```bash
     python3 -m devscripts.cli.sdd phase checklist
     ```

4. **Punto de Control Humano**:
   - Presentar los criterios de calidad al desarrollador para su aprobación antes de avanzar a la Fase 5 (`/sdd-tasks`).

5. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para desglosar el plan técnico en tareas ejecutables ordenadas:
1. Ejecutar `/sdd-tasks` para generar la lista ordenada de tareas de implementación (`tasks.md`).
```
