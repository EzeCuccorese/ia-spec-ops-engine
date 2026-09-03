# SDD Agent Workbench: Java Payment Orders API Demo

Entorno aislado e interactivo para ejecutar el ciclo de vida completo de **Spec-Driven Development (SDD)** con agentes de Inteligencia Artificial (Google Gemini) sobre una aplicación real en **Java / Spring Boot**.

---

## Estructura del Toolkit

```
packages/sdd-workbench/
├── .env.example              # Plantilla de configuración segura
├── runner/                   # Orquestador y TUI en Python
│   ├── sdd_runner_tui.py     # Script interactivo principal con TUI en Rich
│   ├── clean_workbench.py    # Runner para limpiar y dejar el entorno 100% prístino
│   ├── gemini_client.py      # Conector con ADC a Agent Platform (gemini-flash-latest)
│   └── agent_roles.py        # Prompts especializados (SpecAuthor, Craftsman, Judge)
├── test-sdd/                 # Proyecto objetivo en Java 21 / Spring Boot
│   ├── build.gradle          # Configuración con Gradle, JUnit 5, AssertJ y JaCoCo
│   ├── gradlew               # Gradle wrapper ejecutable
│   ├── .spec/                # Gobernanza del arnés (policy.json, verification.json)
│   └── src/                  # Código Java generado bajo TDD
```

---

## Cómo Ejecutarlo

1. **Configuración de Variables de Entorno**:
   Copia el archivo `.env.example` a `.env` en este directorio:
   ```bash
   cp packages/sdd-workbench/.env.example packages/sdd-workbench/.env
   ```
   Edita `.env` y coloca tu `GEMINI_API_KEY` (obtenida en [Google AI Studio](https://aistudio.google.com/)).

2. **Ejecutar el Runner Interactivo por Consola**:
   ```bash
   python3 packages/sdd-workbench/runner/sdd_runner_tui.py
   ```

3. **Flujo de Interacción Humana**:
   * **Fase 1 (Spec)**: El agente redacta `spec.md` con escenarios Gherkin `@s1`, `@s2`, `@s3`. El TUI te muestra el resultado formateado y solicita confirmación.
   * **Fase 2 (Plan)**: El agente de arquitectura genera `plan.md` y `tasks.md` respetando las reglas de Java limpio (records, inmutabilidad, constructor injection).
   * **Fase 3 (TDD)**:
     * Ciclo Rojo: Genera el test JUnit 5 y corre `./gradlew test` (falla).
     * Ciclo Verde: Genera la implementación mínima en Java y corre `./gradlew test` (pasa 100%).
     * Registra la bitácora `work.md` en disco.
    * **Fase 4 (Verificación y Juicio)**:
      * Ejecuta `spec verify` auditando la trazabilidad de todos los escenarios.
      * El Agente **The Judge** audita el código contra YAGNI y emite el veredicto `APPROVED`.
    * **Fase 5 (Sello y Limpieza)**: El sistema te pide confirmación final y ejecuta `spec finish`. Al concluir, te ofrece limpiar automáticamente el entorno.

4. **Limpiar y Resetear el Entorno en Cualquier Momento**:
   Para resetear el proyecto a un estado 100% limpio y prístino:
   ```bash
   python3 packages/sdd-workbench/runner/clean_workbench.py
   # O de forma directa sin confirmación:
   python3 packages/sdd-workbench/runner/clean_workbench.py --force
   ```
