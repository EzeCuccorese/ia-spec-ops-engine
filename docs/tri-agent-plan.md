# TriAgentTaskFlow (Plan · Build · Judge): Antigravity + Claude Code + Codex CLI

> **Origen y cierre del plan:** diseño consolidado el 2026-10-26 entre el usuario, Antigravity, Claude Code y Codex.
> **Estado:** **En ejecución.** Paso 1 completo e instalado (2026-10-26); Pasos 2 y 3 pendientes.
> **Base:** el motor (`ai-governance` + `ws`) **ya está andando y bien**. Este plan se apoya en lo que ya funciona y define cómo coordinar los tres agentes sobre **TriAgentTaskFlow**, el módulo del motor que gobierna el ciclo de vida de cada tarea.

---

## 0. Nombre

El flujo y su módulo en el motor se llaman **TriAgentTaskFlow** (`ai-governance taskflow`). El nombre refleja lo que hace: no es una lista pasiva de pasos, sino el motor que **abre la tarea solo, pasa la posta entre los tres roles (Plan · Build · Judge) y exige evidencia antes de cerrar**.

---

## 1. Contexto y premisas operativas

Tres herramientas con suscripción activa y el motor (`ai-governance` + `ws`) operativo en la máquina:

| Herramienta | Identificador en el motor | Plan | Modelos que vamos a usar | Versión instalada ✅ |
|---|---|---|---|---|
| **Antigravity** | `antigravity` | Business | **Gemini 4 Argon** (1M contexto, multimodal), **Gemini 3.8 Flash** (tareas acotadas / `scout`) | 1.4.6 |
| **Claude Code** | `claude` | Max 5x | **Sonnet 5.5** (default), **Opus 5.5** / **Fable 5.1** (complejo), **Haiku 5.5** (`scout` / `runner`) | 2.1.310 |
| **Codex CLI** | `codex` | Pro | **GPT-6.1 Sol** (juez / análisis), **GPT-6 Luna** (tareas acotadas / `scout`) | 0.164.0 |

### Premisas definidas por el usuario

1. **Usamos `antigravity` para todo; `agy` no lo adoptamos.** Ni como nombre en la documentación ni como alias en el motor. El identificador único es `antigravity`.
2. **Antigravity tiene el mayor cupo de las tres cuentas.** Por eso absorbe toda la lectura pesada, exploración multi-repo, análisis de contexto y planificación.
3. **Astra queda descartado en Codex por ser muy caro.** En Codex usamos **Sol** (`gpt-6.1-sol`, modelo por defecto en `~/.codex/config.toml`) para juzgar y **Luna** (`gpt-6-luna`) para lo liviano/subagentes.
   - **Consecuencia de diseño:** Como Codex no va a usar Astra, el razonamiento pesado de arquitectura y desbloqueo profundo recae en **Antigravity (Argon)** y la implementación compleja en **Claude (Opus 5.5 / Fable 5.1)**. De esa forma, cuando el trabajo llega a Codex para ser juzgado, ya llega con alcance acotado, criterios claros, diff concreto y evidencia determinística: un escenario donde **Sol** rinde al máximo sin gastar en Astra.
4. **Presupuesto monetario (750 USD) desinstalado e inactivo (no se borra el código).** ✅ Ya no importa medir ni limitar gasto en USD. El código de `telemetry` (`claude_usage.py`, `prices.py`, `schedule.py`, etc.) **se conserva inactivo en el repositorio**, pero **no se instala**: quedan fuera de la instalación la regla `claude-usage-budget.md`, el LaunchAgent diario de precios y el hook `Stop` de alertas de gasto. Lo único que importa operativamente es la disponibilidad de cupo/ventana de cada herramienta.

---

## 2. Roles: Separación de poderes (`Plan · Build · Judge`)

El usuario definió tres responsabilidades separadas: **uno planifica, otro valida y codifica, y un tercero juzga**. Ningún agente es juez y parte de su propio código:

| IA | Rol | Modelo Default | Para lo complejo / apoyo |
|---|---|---|---|
| **Antigravity** | **Planificador:** investiga, lee contexto largo, define alcance, criterios de aceptación, plan y verificaciones requeridas | Gemini 4 Argon | Argon (modo High); Flash 3.8 para `scout` y lecturas mecánicas |
| **Claude Code** | **Validador e Implementador:** contrasta el plan contra el repo, codifica, corre los tests/checks y ejecuta el cierre una vez aprobado | Sonnet 5.5 | Opus 5.5 / Fable 5.1 (implementación o bugs difíciles) |
| **Codex** | **Juez independiente:** evalúa el trabajo entregado contra el plan y la evidencia ejecutada; aprueba o devuelve observaciones | GPT-6.1 Sol | GPT-6 Luna para `scout` / chequeos rápidos *(Astra no se usa)* |

- **En tareas chicas:** se mantienen los tres roles pero con entregas mínimas (un plan de pocos renglones, cambio directo y juicio rápido sobre el diff).

---

## 3. Flujo de una tarea

| Fase | Responsable | Qué hace y condición para avanzar |
|---|---|---|
| **0. Apertura automática** | Motor (TriAgentTaskFlow) | **Se activa solo** al tomar una tarea nueva (por branch/ticket o inicio de sesión), vinculando repo, branch y worktree sin intervención manual. |
| **1. Investigar y planificar** | **Antigravity** (Argon) | Lee el contexto necesario, define objetivo, archivos/líneas clave (`path:L10-L50`), criterios de aceptación, riesgos y comandos de verificación. |
| **2. Validar el plan** | **Claude Code** | Contrasta supuestos del plan con el código real antes de editar. Si cierra, avanza a codificar; si ve un hueco en el plan, lo devuelve a Antigravity. |
| **3. Codificar y verificar** | **Claude Code** | Implementa el cambio, ejecuta las pruebas y `ws check --changed`, y deja asentados en TriAgentTaskFlow el diff, los tests corridos y sus resultados. |
| **4. Juzgar el trabajo** | **Codex** (Sol) | Revisa que el diff cumpla el objetivo y el plan, y que la evidencia de pruebas corresponda al código actual. Dictamina: **Aprobado**, **Requiere cambios** o **Falta evidencia**. |
| **5. Corregir (si aplica)** | **Claude → Codex** | Claude aplica las correcciones señaladas por el juez, re-ejecuta verificaciones y Codex valida el ajuste. |
| **6. Cerrar** | **Claude Code** | Con el dictamen favorable de Codex y el quality gate en verde, hace push/PR, actualiza Jira y cierra la tarea en TriAgentTaskFlow. |

### Reglas operativas

1. **TriAgentTaskFlow tiene que andar solo al tomar una tarea nueva.** El desarrollador no tiene que acordarse de correr comandos manuales de inicialización cada vez que arranca un ticket: al detectar una tarea o branch nueva, el sistema debe abrir o asociar el registro automáticamente, cargar el contexto al iniciar sesión y actualizar el estado en cada fase.
2. **Antigravity planifica; Claude valida e implementa; Codex juzga.** Si durante la implementación Claude falla 2 veces en un bug complejo, registra las hipótesis y el fallo en TriAgentTaskFlow y se apalanca en **Antigravity (Argon)** o en **Codex (Sol)** para el diagnóstico, manteniendo la edición del código productivo en Claude.
3. **Una sola IA escribe por branch.** Cualquier prueba o exploración en paralelo va en un worktree separado (`ws`).
4. **Desacuerdos se resuelven con evidencia.** Un test reproducible, el resultado de un comando o el contrato del código mandan sobre la opinión de cualquier modelo. Si es una decisión de negocio o alcance, define el usuario.
5. **Contexto limpio para implementar.** Antigravity condensa el hallazgo en referencias exactas y criterios concretos dentro de TriAgentTaskFlow para que Claude entre directo a validar y codificar sin quemar su ventana leyendo decenas de archivos.

---

## 4. Evolución del motor: TriAgentTaskFlow + lo mejor de `spec`

El motor (`ai-governance` + `ws`) **ya funciona bien** y TriAgentTaskFlow resuelve hoy:
- Persistencia fuera del chat (`~/.local/state/ai-governance/taskflow/tasks/<id>.json` y `.md`).
- Escritura atómica y lock exclusivo por archivo (`fcntl.flock`), evitando corrupción si dos procesos tocan la misma tarea.
- Compactación automática (`summary` ≤ 500 chars, hasta 8 pasos activos, archivo automático de pasos completados en el `.md` y `digest` de 400 chars en el inicio de sesión de Claude).
- Soporte multi-repo (`repos` con `path`, `branch`, `pr`, `worktree`).

### Qué sumamos al motor (sin revivir `spec` como herramienta separada)

`spec` guardaba estado en `.spec/` dentro de cada repo individual, lo que choca con tareas multi-repo y duplica a TriAgentTaskFlow. Por eso **trabajamos únicamente con TriAgentTaskFlow** y le incorporamos tres capacidades clave:

1. **Arranque y vinculación automática en cada tarea nueva (prioridad #1):**
   - Si el agente arranca en una branch con clave de ticket (ej. `ONB-XXXX`) o recibe un ticket nuevo y la tarea no existe en TriAgentTaskFlow, se crea y vincula sola al repo/worktree actual.
   - Si se abre un worktree adicional para la misma tarea, se asocia automáticamente sin perder el vínculo con el repo principal.
   - Los tres agentes (`antigravity`, `claude`, `codex`) deben recibir el estado activo al iniciar su intervención, no solo Claude.
2. **Fases rescatadas de `spec` (`Stage`):**
   - Incorporar el estado de fase en TriAgentTaskFlow alineado al flujo: `plan` (Antigravity) → `validate` / `work` (Claude) → `judge` (Codex) → `done` (Claude), registrando qué agente hizo cada paso (`--agent antigravity|claude|codex`).
3. **Evidencia vinculada al código rescatada de `spec` (`CheckResult` + huella del árbol):**
   - Registrar qué verificaciones se corrieron (`ws check --changed`, tests puntuales), su resultado (`PASS`/`FAIL`) y la huella del código (`HEAD` SHA + estado de archivos sin commit por cada repo) en ese instante.
   - Igual que hacía `finish()` en `spec`, si alguien modifica el código después de verificar o después del dictamen de Codex, la evidencia queda marcada como desactualizada (`stale`) y exige re-verificar antes de cerrar.

---

## 5. Instrucciones y configuración de agentes (`AGENTS.md`)

- **`GEMINI.md` no existe más:** fue deprecado en nuestro entorno y `ai-governance doctor` ya lo trata como legado a eliminar. Antigravity carga sus reglas desde `~/.gemini/config/rules/` (global), `.agents/rules/` (proyecto) y `AGENTS.md`.
- **`AGENTS.md` + `.agents/rules/` como fuente única en los repos:** tanto Antigravity como Codex y Claude Code (≥ 2.1.277) leen `AGENTS.md` en la raíz del repositorio.
- **`CLAUDE.md` (resuelto 2026-10-26):**
  - En los repos, `installer.py` ya migra y borra `CLAUDE.md` porque su presencia hace que Claude Code ignore `AGENTS.md` por defecto.
  - En el alcance global (`~/.claude/`) **el stub `~/.claude/CLAUDE.md` (`@AGENTS.md`) se queda**: es lo único que hace que Claude Code cargue `~/.claude/AGENTS.md`. Prueba: con el stub, Claude responde una instrucción que solo está en `~/.claude/AGENTS.md`; sin el stub, no la conoce. `~/.claude/rules/*.md` sí se carga solo.
- **Subagentes en Codex:** ✅ el instalador (`CodexSpec` y `probe.py`) configura el subagente `scout` con **`"gpt-6-luna"`** (`GPT-6-Luna`; el nombre corto `luna` no es un modelo válido) en vez de `"terra"`, manteniendo **Sol** para el agente principal y sin usar Astra en ningún perfil.

---

## 6. Hoja de ruta de ejecución

> Cada paso se ejecuta cuando el usuario lo indica.

### Paso 1 — Desinstalar y dejar inactivo lo deprecado (Presupuesto 750 USD y ajuste de `CodexSpec`) — ✅ implementado (2026-10-26, sin commit)
- [x] Eliminar la regla `claude-usage-budget.md`: se borró el archivo del pack `tiendanube` y la reinstalación quitó sus symlinks de `~/.gemini/config/rules/` y `~/.claude/rules/`.
- [x] Desenganchar de la instalación el LaunchAgent `com.ai-governance.prices-update` (`schedule.py`): ya no se instala ni se carga, y el instalador para y borra el plist que haya quedado de versiones anteriores.
- [x] Quitar el hook global `Stop` de alertas de gasto (`telemetry thresholds --notify`) de `ClaudeSpec`; `_claude_stop` en `hooks.py` queda en el código, inactivo. El `Stop` de `stop-gate` a nivel proyecto no cambia.
- [x] **Todo el código de `telemetry` y precios queda intacto pero inactivo.** `schedule.unload()` también retira el servicio legado `com.cucco.claude-uso-precios`, para que una instalación vieja no siga actualizando precios.
- [x] `CodexSpec` y `probe.py` configuran `gpt-6-luna` en vez de `terra` (README y `docs/getting-started.md` actualizados).
- [x] Verificación: 609 tests de `ai-governance` en verde y `ws check --changed` → `gate: passed`.
- [x] Instalado en la máquina: `ai-governance` (uv tool, editable) apunta a este worktree y se reinstaló el alcance de usuario para `claude`, `antigravity` y `codex`.
- [x] Instalar el alcance de usuario para `codex`: bloque en `~/.codex/AGENTS.md` y `~/.codex/config.toml` (subagentes en `gpt-6-luna`), `~/.codex/agents/scout.toml` y skills en `~/.agents/skills/`. Codex no tiene reglas globales por archivo, así que las del pack `tiendanube` no le llegan. Sus hooks se activan recién después de `ai-governance probe --agent codex`.
- [x] Prueba de `CLAUDE.md` global: hace falta el stub `@AGENTS.md` (ver sección 5).

### Paso 2 — Piloto en 2–3 tickets reales con TriAgentTaskFlow
- [ ] Ejecutar el circuito **Antigravity (planifica con Argon) → Claude (valida e implementa con Sonnet/Opus) → Codex (juzga con Sol) → Claude (cierra)** apoyándose en el motor actual.
- [ ] Medir en la práctica dónde hay fricción real al pasar la posta entre los tres agentes.

### Paso 3 — Ajustes en TriAgentTaskFlow (Motor)
- [ ] Hacer que TriAgentTaskFlow **arranque y vincule solo** cada tarea nueva (por branch/ticket/worktree) y exponga el contexto de inicio en los tres agentes.
- [ ] Sumar a TriAgentTaskFlow las fases (`plan`, `work`, `judge`, `done`), la atribución por agente (`--agent antigravity|claude|codex`), el armado de traspaso (`handoff` con filtro de secretos) y el registro de evidencia atado al commit/árbol (`evidence` rescatado de `spec`).
