---
name: sdd-audit
description: "Auditoría integral de base de código: detecta deuda técnica, bugs, anti-patrones, fugas de memoria y genera planes de ataque estructurados en .specify/tech-debt.md con bloques de remediación listos para ejecutar."
argument-hint: "[--repo <nombre-repo>] [--deep] [--scope <modulo>]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
disable-model-invocation: true
---

# SDD Audit — Auditoría Integral de Deuda Técnica, Bugs y Anti-Patrones

Estás ejecutando la habilidad **SDD Technical Debt & Bug Audit**. Esta habilidad realiza un análisis estático y estructural exhaustivo del repositorio o módulo objetivo para identificar anti-patrones, fragilidades, bugs potenciales, violaciones a la arquitectura SDD, problemas de seguridad/observabilidad y deuda en persistencia/migraciones, catalogando todos los hallazgos en `.specify/tech-debt.md` junto con una matriz de impacto y planes de ataque accionables.

---

## 👥 Roles Multi-Agente Especializados (Arquitectura Spec-Kit)

1. 👑 **Agente Líder Orquestador**:
   - Administra el alcance de la auditoría y coordina la ejecución.
   - Invoca al **Especialista en Auditoría de Deuda Técnica** y al **Validador QA de Estrategia de Remediación** mediante `invoke_subagent`.
   - Controla el bucle de auto-corrección autónomo (máximo 3 reintentos antes de elevar al usuario).

2. 🛠️ **Agente Especialista de Fase (Technical Debt Audit Specialist)**:
   - Inspecciona la base de código sobre 5 ejes críticos (Calidad, SDD, Seguridad/Observabilidad, Persistencia, Marcadores).
   - Diseña planes de ataque detallados para resolver los hallazgos.

3. 🔍 **Agente Validador de Calidad (Remediation Strategy QA Agent)**:
   - Audita de forma adversarial el catálogo `.specify/tech-debt.md` verificando que los diagnósticos sean precisos y que los comandos de remediación `/sdd-quick` sean sintácticamente correctos.

---

## ⚡ Protocolo Híbrido para Habilidades de Agentes (Determinismo + Validación Dinámica de IA)
Al ejecutar esta habilidad, el agente DEBE cumplir 3 fases:
1. **Fase 1 (Determinística)**: Ejecutar herramientas CLI / scripts estáticos (`sdd ...`).
2. **Fase 2 (Auditoría Dinámica de IA)**: Inspeccionar el código fuente del repositorio.
3. **Fase 3 (Enriquecimiento Explícito)**: Inyectar las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md`.

---

## 📋 Pasos de Ejecución

### Paso 0: Validar Parámetros y Estado Inicial
1. **Verificar Parámetros de Alcance**:
   - Si se especifica `--scope <modulo>` o `--repo <nombre>`, validar la existencia de las rutas en el repositorio.
   - Inicializar el directorio `.specify/` si no existe.


---

## 📋 Modos de Operación

1. **Modo Global / Deep (`/sdd-audit --deep`)**:
   - Escanea la totalidad del repositorio en busca de deuda técnica general y anti-patrones sistémicos.
2. **Modo Integrado / Micro-Audit (`/sdd-audit --scope <modulo>`)**:
   - Se ejecuta de forma previa a la fase de planificación (`/sdd-plan`) para auditar específicamente los módulos que serán modificados por una nueva característica.

---

## 🔍 Ejes de Inspección Exhaustiva

### A. Calidad de Código y Arquitectura
- **Archivos Gigantes / Clases Dios**: Archivos con más de 400 líneas o clases con acoplamiento de responsabilidades.
- **Acoplamiento Directo**: Controladores realizando consultas directas a base de datos o lógica de negocio sin pasar por servicios.
- **Duplicación de Código**: Bloques de lógica repetidos sin abstracción.

### B. Adherencia a Spec-Driven Development (SDD)
- **Contratos Ausentes**: Endpoints HTTP o APIs sin esquemas Zod (TypeScript) o Records/DTOs inmutables (Java).
- **Falta de Harnés de Pruebas**: Lógica crítica sin pruebas unitarias (JaCoCo $< 85\%$ o cobertura deficiente).

### C. Seguridad y Observabilidad
- **Secretos Hardcodeados**: Patrones de API keys, contraseñas, tokens JWT o certificados en código fuente.
- **Fuga de PII en Logs**: Registro de datos personales sensibles (emails, DNI, tarjetas).
- **Falta de Trazabilidad**: Ausencia de propagación de cabeceras de correlación (`X-Request-Id`, `X-Trace-Id`).
- **Excepciones Silenciadas**: Bloques `catch` vacíos o captura genérica sin logging estructurado.

### D. Persistencia y Base de Datos
- **Consultas Ineficientes (N+1)**: Bucles iterativos ejecutando consultas individuales a la base de datos.
- **Migraciones Frágiles**: Cambios de esquema sin scripts versionados (Flyway/Liquibase) o `@ChangeUnit` de Mongock sin `@RollbackExecution`.
- **Falta de Backups Previos**: Mutaciones directas de datos sin respaldo JSON previo.

### E. Marcadores de Deuda en Comentarios
- Detección de marcadores `TODO`, `FIXME`, `HACK`, `DEPRECATED`, `XXX` o `TEMP`.

---

## 📄 Estructura Generada: `.specify/tech-debt.md`

El entregable debe estructurarse con la siguiente plantilla estandarizada:

```markdown
# 📊 Catálogo de Deuda Técnica, Bugs y Anti-Patrones

**Repositorio**: `{repo-name}`  
**Fecha de Auditoría**: {YYYY-MM-DD}  
**Estado General**: 🟡 REQUIERE ATENCIÓN / 🔴 ALTO RIESGO / 🟢 SALUDABLE  
**Puntaje de Deuda**: {X Críticos, Y Altos, Z Medios, W Bajos}  

---

## 🎯 Resumen Ejecutivo
{Síntesis diagnóstica del estado de la base de código y prioridades recomendadas.}

---

## 📈 Matriz de Prioridad e Impacto
- 🔴 **CRÍTICO**: Vulnerabilidades de seguridad, secretos expuestos, riesgo de pérdida de datos.
- 🟠 **ALTO**: Lógica de negocio crítica sin tests unitarios, consultas N+1, bordes HTTP sin contratos.
- 🟡 **MEDIO**: Clases Dios, código duplicado, falta de logger estructurado.
- 🟢 **BAJO**: TODOs informativos, comentarios obsoletos, inconsistencias menores de formato.

---

## 📑 Catálogo Detallado de Hallazgos y Planes de Ataque

### 🔴 Hallazgos Críticos

#### `[TD-001]` {Título del Hallazgo Crítico}
- **Categoría**: {Seguridad | Persistencia | SDD | Calidad}
- **Ubicación**: [`{path/to/file.ext}:L{line}`](file://{absolute_path}#L{line})
- **Descripción**: {Explicación detallada del problema y su riesgo.}
- **Impacto Potencial**: {Consecuencia en producción o mantenibilidad.}
- **Plan de Ataque y Remediación**:
  1. Paso 1: {Acción técnica concreta}.
  2. Paso 2: {Acción de verificación y test}.
- **Comando de Remediación SDD (Copiar y Pegar)**:
  ```bash
  /sdd-quick "Corregir [TD-001]: <descripcion_corta> en <file_path>"
  ```

---

## 🛠️ Plan de Acción Sugerido
1. **Fase 1 (Inmediata)**: Resolver hallazgos 🔴 Críticos mediante `/sdd-quick`.
2. **Fase 2 (Corto Plazo)**: Implementar contratos Zod/DTOs y tests para hallazgos 🟠 Altos.
3. **Fase 3 (Mantenimiento)**: Refactorizar módulos 🟡 Medios en próximos ciclos.
```
