---
name: sdd-plan
description: "Fase 3 de SDD: Diseña la solución técnica (plan.md), definiendo contratos formales de datos, diagramas Mermaid y estrategia arquitectónica."
argument-hint: "<nombre-del-feature>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Plan — Fase 3: Blueprint Técnico y Contratos

Paso 3 del ciclo de vida de **Spec-Driven Development (SDD)**. Diseña la solución técnica basada en `spec.md` y `clarify.md`:

```
.specify/specs/<nombre-del-feature>/plan.md
```

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Software Architect Agent** y al **Contract Validator QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Software Architect Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Contract Validator QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-plan <parámetros>`).


1. **Obtener Feature Activo**:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   FEATURE_NAME="$(python3 -m devscripts.cli.sdd feature)"
   FEATURE_DIR="$REPO_ROOT/.specify/specs/$FEATURE_NAME"
   ```

2. **Diseñar Blueprint Técnico**:
   - Definir módulos y capas afectadas (Controlador, Servicio, Persistencia).
   - Escribir diagrama de secuencia en formato **Mermaid**.
   - Definir **Contratos Primero (Pilar 1 de SDD)**: esquemas Zod, interfaces TypeScript o DTOs Java.
   - Definir estrategia de persistencia en base de datos (Mongock / Flyway / respaldo JSON obligatorio previo a mutación en MongoDB).
   - Elaborar Matriz de Riesgo e Impacto.

3. **Guardar `plan.md` y Actualizar Estado**:
   - Escribir `$FEATURE_DIR/plan.md`.
   - Actualizar estado de la fase:
     ```bash
     python3 -m devscripts.cli.sdd phase plan
     ```

4. **Punto de Control Humano**:
   - Presentar el plan arquitectónico y los contratos al usuario para su aprobación antes de avanzar a la Fase 4 (`/sdd-checklist`).

5. **🎯 Próximos Pasos Recomendados**:
   - Finalizar SIEMPRE la respuesta mostrando la sugerencia para la siguiente fase:

```markdown
### 🎯 Próximos Pasos Recomendados

Para definir las Quality Gates y la Definition of Done:
1. Ejecutar `/sdd-checklist` para establecer los criterios de verificación y pruebas requeridas (`checklist.md`).
```
