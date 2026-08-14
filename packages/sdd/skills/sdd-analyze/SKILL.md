---
name: sdd-analyze
description: "Fase 6 de SDD: Valida la consistencia cruzada de artefactos entre spec.md, clarify.md, plan.md, checklist.md, tasks.md y la constitución del proyecto."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Analyze — Fase 6: Auditoría Estática de Consistencia Cruzada

Paso 6 del ciclo de vida de **Spec-Driven Development (SDD)**. Realiza una verificación estática para garantizar que todos los artefactos estén 100% alineados antes de escribir código de producción:

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Static Consistency Auditor Agent** y al **Cross-Artifact QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Static Consistency Auditor Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Cross-Artifact QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-analyze <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   python3 -m devscripts.cli.sdd feature
   ```

2. **Ejecutar Analizador Estático**:
   ```bash
   python3 -m devscripts.cli.sdd analyze
   ```

3. **Verificar Reglas Cruzadas entre Artefactos**:
   - ¿Cada requerimiento en `spec.md` tiene su tarea correspondiente en `tasks.md`?
   - ¿`plan.md` define los contratos obligatorios para las tareas de la Fase 1?
   - ¿`checklist.md` incluye todas las reglas de la constitución?

4. **Actualizar Estado de Fase y Reportar**:
   - Actualizar la fase activa a `analyze`.

5. **Punto de Control Humano**:
   - Presentar el reporte de auditoría al desarrollador. Solicitar aprobación explícita humana antes de iniciar la ejecución (`sdd exec`).

6. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para iniciar la ejecución iterativa de tareas con el arnés multi-agente:
1. Ejecutar `/sdd-exec` para comenzar la implementación con el agente Worker y QA Reviewer.
```

