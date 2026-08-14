---
name: sdd-quick
description: "Ruta de ejecución acelerada estrictamente acotada para correcciones de bugs, parches menores o hotfixes."
argument-hint: "<descripción-del-bug o id-del-issue>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Quick — Ruta Acelerada para Bugs y Hotfixes

Atajo acelerado reservado estrictamente para **correcciones de bugs, parches menores o refactorizaciones pequeñas**.

> [!WARNING]
> Esta habilidad está acotada estrictamente a correcciones pequeñas de bugs. Para el desarrollo de nuevas características o refactorizaciones estructurales, es obligatorio utilizar el ciclo de vida estándar de 8 fases (`sdd-specify`, `sdd-clarify`, `sdd-plan`, `sdd-checklist`, `sdd-tasks`, `sdd-analyze`, `sdd-exec`, `sdd-converge`).

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Hotfix Worker Agent** y al **Quick QA Reviewer Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Hotfix Worker Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Quick QA Reviewer Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-quick <parámetros>`).


1. **Crear Especificación Rápida de Bug**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   BUG_ID="quick-$(date +%s)"
   QUICK_DIR="$REPO_ROOT/.specify/specs/$BUG_ID"
   mkdir -p "$QUICK_DIR"
   ```

2. **Escribir `spec-quick.md`**:
   - **Bug Identificado**: Descripción clara del comportamiento erróneo.
   - **Comportamiento Esperado**: Resultado correcto esperado.
   - **Prueba de Reproducción (Rojo)**: Prueba que falla demostrando el bug.
   - **Solución Acotada (Verde)**: Modificación mínima de código para reparar el bug sin alterar archivos no relacionados.

3. **Ejecutar Reparación Acotada**:
   - Escribir prueba unitaria de regresión.
   - Implementar la solución.
   - Ejecutar linter y suite de pruebas.

4. **Verificación de Reglas Globales**:
   - Lectura de confirmación tras mutación.
   - Auditoría de cero PII y cero secretos en logs.
   - Formatear mensaje de commit en **Conventional Commits** (`fix(scope): description`) sin menciones de IA.
