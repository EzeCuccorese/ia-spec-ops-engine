---
name: sdd-init
description: Inicializa el espacio de trabajo SDD con protocolo híbrido (Determinismo CLI + Validación y Descubrimiento Dinámico de IA).
---

# Habilidad SDD Init — Protocolo Híbrido

Esta habilidad inicializa el espacio de trabajo de Spec-Driven Development (SDD) en el repositorio actual combinando la ejecución determinística CLI con la inspección dinámica de la IA para capturar buenas prácticas del proyecto.

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Environment Setup Specialist** y al **Dynamic Repository Audit QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Environment Setup Specialist)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Dynamic Repository Audit QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-init <parámetros>`).

## 📋 Protocolo de Ejecución de 3 Pasos

### Paso 1: Ejecución Determinística CLI con Banderas Explícitas de IA
1. **Verificar o Consultar Adaptadores**: Si el usuario no especificó explicitamente qué agentes de IA desea activar (ej: `claude`, `cursor`, `all`), seleccionar por defecto el entorno activo (ej: `--agy` para Google Antigravity).
2. **Ejecutar Inicialización con Flags Explícitos**:
   `python3 -m devscripts.cli.sdd.sdd init --agy` (o con los flags correspondientes `--claude`, `--copilot`, etc.)

Esto realiza las tareas determinísticas iniciales:
- Auto-detecta e inicializa la constitución del proyecto (`.specify/constitution/constitution.md`).
- Inicializa la estructura de memoria (`.specify/memory.md`).
- Genera/actualiza **únicamente** los adaptadores de IA explícitamente solicitados en `agents.json`, preservando 100% intacto cualquier otro archivo previo del repositorio (como `.cursorrules` o `CLAUDE.md`).

### Paso 2: Auditoría & Validación Dinámica del Repositorio por IA
Tras la ejecución determinística, la IA debe inspeccionar el repositorio para detectar patrones y convenciones específicas del proyecto que se le escapen a la herramienta determinística:
1. **Manifests & Dependencias**: Inspeccionar `pyproject.toml`, `package.json`, `pom.xml`, `build.gradle`, `Cargo.toml`, `go.mod`, `pubspec.yaml`, etc.
2. **Linters & Formatters**: Detectar herramientas como `ruff`, `eslint`, `oxlint`, `checkstyle`, `ktlint`, `prettier`, etc.
3. **Harnés de Pruebas**: Identificar la suite de pruebas y comando de ejecución (`pytest`, `vitest`, `./gradlew test`, `npm test`, `flutter test`, etc.).
4. **Patrones Arquitectónicos**: Analizar la estructura de carpetas (`src/`, `lib/`, `domain/`, etc.), patrones de diseño (inyección por constructor, DTOs, mappers) y convenciones específicas del proyecto.

### Paso 3: Enriquecimiento Explícito de Artefactos y Reporte
1. Inyectar formalmente las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md` y `.specify/memory.md` en la sección dedicada:
   `## 🔍 Descubrimientos Dinámicos de IA & Buenas Prácticas del Proyecto`
3. **MANDATORIO**: Finalizar SIEMPRE la respuesta mostrando la sección exacta de continuidad:

```markdown
### 🎯 Próximos Pasos Recomendados

Para comenzar a definir una nueva característica o requerimiento en el ciclo SDD:
1. Ejecutar `/sdd-specify <nombre-feature>` para redactar la especificación funcional inicial (`spec.md`).
```
