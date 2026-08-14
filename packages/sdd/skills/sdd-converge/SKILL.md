---
name: sdd-converge
description: "Fase 8 de SDD: Valida la convergencia final, ejecutando la suite completa de pruebas, auditoría de checklist y escenarios Gherkin antes del commit/PR."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Converge — Fase 8: Convergencia Final y Verificación de Cierre

Paso 8 del ciclo de vida de **Spec-Driven Development (SDD)**. Realiza la verificación final de convergencia en la característica antes de declarar el trabajo completado o solicitar autorización para commit/PR:

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Release Manager Agent** y al **Gherkin Verification QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Release Manager Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Gherkin Verification QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-converge <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   FEATURE_NAME="$(python3 -m devscripts.cli.sdd feature)"
   FEATURE_DIR="$REPO_ROOT/.specify/specs/$FEATURE_NAME"
   ```

2. **Ejecutar Suite Completa de Pruebas Automatizadas**:
   ```bash
   # Según el stack detectado:
   npm test 2>/dev/null || ./gradlew test 2>/dev/null || pytest 2>/dev/null || true
   ```

3. **Verificación de Criterios de Aceptación Gherkin**:
   - Confirmar punto por punto cada escenario definido en `$FEATURE_DIR/spec.md`.

4. **Auditoría de Lista de Calidad (`checklist.md`)**:
   - Validar que todas las casillas en `$FEATURE_DIR/checklist.md` estén marcadas.

5. **Auditoría de Git y Formato**:
   - `git status` para verificar archivos modificados.
   - Confirmar que los mensajes de commit sigan **Conventional Commits** (`type(scope): description`).
   - Confirmar **CERO menciones a IA o emojis de robot**.

6. **Actualizar Estado del Feature**:
   ```bash
   python3 -m devscripts.cli.sdd phase converge
   ```

7. **Ejecutar Cierre Automático, Push, PR y Limpieza de Worktree**:
   ```bash
   python3 -m devscripts.cli.sdd finish
   ```
   Esto automatiza los siguientes pasos:
   - Empuja la rama de característica a origin (`git push -u origin feature/<nombre>`).
   - Crea el Pull Request en GitHub con `gh pr create`.
   - Elimina el Worktree local limpiamente (`git worktree remove --force`).
   - Retorna a la carpeta principal del repositorio, cambia a la rama `main` y ejecuta `git pull origin main`.

8. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia de continuidad:

```markdown
### 🎯 Próximos Pasos Recomendados

La característica ha convergido exitosamente, el Pull Request fue creado y el Worktree fue removido.
1. La rama `main` local ha sido actualizada con `git pull origin main`.
2. Para comenzar una nueva característica: `/sdd-specify <nuevo-feature>`.
```
