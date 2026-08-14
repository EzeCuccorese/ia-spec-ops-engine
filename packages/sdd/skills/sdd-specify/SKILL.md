---
name: sdd-specify
description: "Fase 1 de SDD: Genera la especificación funcional (spec.md) con historias de usuario, requerimientos funcionales/NFR y escenarios Gherkin."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Specify — Fase 1: Especificación Funcional

Paso 1 del ciclo de vida de **Spec-Driven Development (SDD)**. Genera la especificación funcional detallada para el feature:

```
.specify/specs/<nombre-del-feature>/spec.md
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Product Owner Agent** y al **QA Business Auditor Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Product Owner Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (QA Business Auditor Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros, Inferencia Inteligente y Confirmación Interactivas
1. **Inferencia Inteligente de Nombre**:
   - Si el usuario proporciona una descripción en lenguaje natural (ej: *"quiero un nuevo producto para ventas de pelotas, hace el plan del crud"*), **la IA infiere un nombre limpio en `kebab-case`** (ej. `crud-venta-pelotas`).

2. **Interrogatorio y Confirmación Interactivas (`AskUserQuestion`)**:
   - Está **ESTRICTAMENTE PROHIBIDO** asumir nombres ("default", "main") o ejecutar mutaciones en el Git Worktree sin la confirmación del usuario.
   - La IA DEBE invocar obligatoriamente `AskUserQuestion` solicitando:
     - **Pregunta 1 (Confirmación de Nombre)**: *"He inferido el nombre de la especificación como `<nombre-inferido>`. ¿Estás de acuerdo o prefieres cambiarlo?"*
     - **Pregunta 2 (Rama Base)**: *"¿Desde qué rama base deseas salir? (`main`, `develop`, `staging`, etc.)"*
     - **Pregunta 3 (Confirmación Final)**: *"Se creará la rama `feature/<nombre>` desde `<rama-base>` e iniciará la Fase 1. ¿Procedemos?"*

3. **Descubrimiento de Features Existentes (Retoma de Sesión)**:
   - Si no se especifica nombre ni frase, ejecutar `python3 -m devscripts.cli.sdd feature list` para mostrar las características existentes en `.specify/specs/` y solicitar al usuario mediante `AskUserQuestion` si desea retomar alguna de la lista o crear una nueva.


1. **Establecer / Confirmar Feature Activo**:
   ```bash
   python3 -m devscripts.cli.sdd feature "$FEATURE_NAME"
   ```

2. **Verificar Constitución del Proyecto**:
   - Leer `.specify/constitution/` para alinear alcance, reglas de arquitectura y estándares.

3. **Generar `spec.md`**:
   - Crear el directorio `.specify/specs/<nombre-del-feature>/`.
   - Copiar/poblar la plantilla de especificación:
     - Resumen Ejecutivo y Alcance de Negocio.
     - Historias de Usuario con roles y beneficios.
     - Requerimientos Funcionales (FR) y No Funcionales (NFR: CWV, seguridad, no PII).
     - Criterios de Aceptación con sintaxis Gherkin (Given-When-Then).

4. **Actualizar Fase y Reportar**:
   - Actualizar fase activa a `specify`.

5. **Punto de Control Humano**:
   - Presentar `spec.md` al usuario y solicitar aprobación explícita antes de pasar a la Fase 2 (`sdd clarify`).

6. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para auditar y resolver ambigüedades en la especificación funcional:
1. Ejecutar `/sdd-clarify` para realizar la resolución de ambigüedades y análisis de riesgos (`clarify.md`).
```
