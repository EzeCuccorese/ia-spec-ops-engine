## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el estado en `.specify/feature.json`, extrae contexto acotado y coordina la ejecución.
   - Invoca a los subagentes especializados utilizando `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Worker / Domain Agent)**:
   - Ejecuta la tarea técnica o de especificación enfocada 100% en su dominio de experiencia.
   - Aplica los 4 Pilares de SDD (Contratos Primero, Test-First, Implementación Mínima, Detección Temprana).

3. 🔍 **Agente Validador de Calidad (QA Reviewer / Auditor Agent)**:
   - Audita de forma adversarial el entregable o el código (linter, tests, contratos, PII, checklist).
   - Aprueba (`PASS`) o rechaza (`FAIL`) con un informe sintáctico de remediación.
