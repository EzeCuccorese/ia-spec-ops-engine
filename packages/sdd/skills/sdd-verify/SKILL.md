---
name: sdd-verify
description: Ejecuta verificaciones automáticas (linter, pruebas unitarias, lecturas GET de confirmación, escaneos de seguridad) para SDD.
---

# Habilidad SDD Verify — Protocolo Híbrido

Ejecuta verificaciones para asegurar la calidad del código y cumplimiento de contratos:
- Ejecutar linters del stack y pruebas unitarias (`pytest`, `oxlint`, `eslint`, `./gradlew check`).
- Ejecutar lecturas de confirmación tras mutaciones (verificaciones GET).
- Escanear en busca de secretos hardcodeados e información sensible (PII).

Uso de CLI:
`python3 -m devscripts.cli.sdd verify`

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca al **Automated Verification Specialist** y al **Security & Code Integrity QA Agent** utilizando la herramienta `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Automated Verification Specialist)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (Security & Code Integrity QA Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetro y Feature Activo**:
   - Si la habilidad requiere un parámetro (ej. `<nombre-del-feature>`), validar que no esté vacío y cumpla formato `kebab-case`.
   - Si no se pasa parámetro, consultar el feature activo ejecutando: `python3 -m devscripts.cli.sdd feature get` o leyendo `.specify/feature.json`.
   - Si **no existe un feature activo** y **no se proporcionó argumento**, **NO continuar con valores vacíos ni caídas por defecto ("default")**.
   - Solicitar al usuario el parámetro mediante `AskUserQuestion` o detener la ejecución informando la sintaxis requerida (`/sdd-verify <parámetros>`).
