"""
sdd_engine.bridge — Generador nativo de adaptadores Multi-IA para Spec-Driven Development (SDD).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sdd_engine.constitution import read_constitution
from sdd_engine.utils import Color, log_info, log_success, log_warning


@dataclass
class RuleDefinition:
    name: str
    description: str
    always_apply: bool
    globs: List[str] = field(default_factory=list)
    content: str = ""
    is_global: bool = False


def _parse_frontmatter(content: str) -> Tuple[Dict[str, any], str]:
    """Parsea frontmatter YAML simple delimitado por --- al inicio del markdown."""
    metadata: Dict[str, any] = {}
    body = content.strip()
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        try:
                            metadata[k] = json.loads(v)
                        except Exception:
                            metadata[k] = [s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()]
                    elif v.lower() in ("true", "yes"):
                        metadata[k] = True
                    elif v.lower() in ("false", "no"):
                        metadata[k] = False
                    else:
                        metadata[k] = v.strip("'\"")
    return metadata, body


def load_rules_catalog(target_dir: str = ".") -> Tuple[List[RuleDefinition], List[RuleDefinition]]:
    """
    Carga y parsea el catálogo de reglas desde rules/ (o .specify/rules/).
    Retorna (global_rules, scoped_rules).
    """
    td = Path(target_dir).resolve()
    base_rules_dir = td / "rules"
    if not base_rules_dir.exists():
        base_rules_dir = td / ".specify" / "rules"

    global_rules: List[RuleDefinition] = []
    scoped_rules: List[RuleDefinition] = []

    if not base_rules_dir.exists() or not base_rules_dir.is_dir():
        return global_rules, scoped_rules

    # 1. Cargar reglas globales
    g_dir = base_rules_dir / "global"
    if g_dir.exists() and g_dir.is_dir():
        for r_file in sorted(g_dir.glob("*.md")):
            raw = r_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", r_file.stem)
            desc = meta.get("description", f"Regla global {name}")
            global_rules.append(
                RuleDefinition(
                    name=name,
                    description=desc,
                    always_apply=True,
                    globs=[],
                    content=body,
                    is_global=True,
                )
            )

    # 2. Cargar reglas scoped
    s_dir = base_rules_dir / "scoped"
    if s_dir.exists() and s_dir.is_dir():
        for r_file in sorted(s_dir.glob("*.md")):
            raw = r_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", r_file.stem)
            desc = meta.get("description", f"Regla scoped {name}")
            globs = meta.get("globs", [])
            always_apply = meta.get("alwaysApply", False)
            scoped_rules.append(
                RuleDefinition(
                    name=name,
                    description=desc,
                    always_apply=always_apply,
                    globs=globs,
                    content=body,
                    is_global=False,
                )
            )

    # Fallback si las reglas están en plano dentro de rules/
    if not global_rules and not scoped_rules:
        for r_file in sorted(base_rules_dir.glob("*.md")):
            raw = r_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", r_file.stem)
            desc = meta.get("description", f"Regla {name}")
            globs = meta.get("globs", [])
            always_apply = meta.get("alwaysApply", True)
            rd = RuleDefinition(
                name=name,
                description=desc,
                always_apply=always_apply,
                globs=globs,
                content=body,
                is_global=always_apply,
            )
            if always_apply:
                global_rules.append(rd)
            else:
                scoped_rules.append(rd)

    return global_rules, scoped_rules


def clean_agents_directory(target_agents_dir: Path) -> list[str]:
    """Limpia directorios legacy de subagentes en .agents/."""
    purged = []
    if not target_agents_dir.exists() or not target_agents_dir.is_dir():
        return purged
    allowed_dirs = {"skills", "rules", "workflows"}
    for child in target_agents_dir.iterdir():
        if child.is_dir() and child.name not in allowed_dirs:
            shutil.rmtree(child, ignore_errors=True)
            purged.append(child.name)
    return purged


def detect_existing_agents(target_dir: str = ".") -> List[str]:
    """Detecta plataformas de agentes de IA activas según la estructura de archivos."""
    td = Path(target_dir).resolve()
    detected: List[str] = []
    if (td / ".agents").exists() or (td / "AGENTS.md").exists():
        detected.append("agy")
    if (td / "CLAUDE.md").exists() or (td / ".claude" / "settings.json").exists():
        detected.append("claude")
    if (td / ".cursorrules").exists() or (td / ".cursor" / "rules").exists():
        detected.append("cursor")
    if (td / ".github" / "copilot-instructions.md").exists():
        detected.append("copilot")
    if (td / ".windsurfrules").exists():
        detected.append("windsurf")
    if (td / ".gemini" / "GEMINI.md").exists():
        detected.append("gemini")
    if (td / "CHATGPT.md").exists():
        detected.append("chatgpt")

    return detected or ["agy"]


def get_sdd_core_rules(target_dir: str = ".") -> str:
    td = Path(target_dir).resolve()
    
    base_rules = """# Spec-Driven Development (SDD) — Reglas Centrales y Ciclo de Vida Paso a Paso

## 1. Ciclo de Vida Estricto (Puntos de Control Humano)
El desarrollo de features DEBE avanzar secuencialmente, requiriendo revisión y aprobación humana antes de iniciar cada fase:
1. `/sdd-specify`: Especificación funcional (`spec.md`).
2. `/sdd-clarify`: Resolución de ambigüedades y análisis de riesgos (`clarify.md`).
3. `/sdd-plan`: Blueprint técnico y contratos formales de datos (`plan.md`).
4. `/sdd-checklist`: Quality gates y Definition of Done (`checklist.md`).
5. `/sdd-tasks`: Desglose atomizado de tareas ejecutables (`tasks.md`).
6. `/sdd-analyze`: Auditoría estática cruzada entre artefactos.
7. `/sdd-exec`: Ejecución iterativa de tareas con Agente Worker y Agente QA.
8. `/sdd-converge`: Verificación final de convergencia y criterios de aceptación Gherkin.

*Nota*: Para correcciones rápidas de bugs, usar exclusivamente `sdd quick`.

## 2. Pilares de SDD
- **Contratos Primero**: Definir interfaces TypeScript, esquemas Zod o DTOs Java antes de implementar la lógica.
- **Harnés de Pruebas (Test-First)**: Escribir pruebas unitarias/integración (Rojo) antes de la lógica de negocio.
- **Implementación Mínima**: Escribir el código estrictamente necesario para cumplir el contrato y pasar la prueba (Verde).
- **Detección Temprana**: Ejecutar linters y verificar lecturas de confirmación tras mutaciones.

## 3. Reglas de Git y Seguridad
- **Conventional Commits**: Escribir mensajes de commit en inglés (`type(scope): description`) en minúsculas e imperativo.
- **ZERO AI MENTIONS / CERO MENCIONES DE IA**: Nunca incluir frases como "Generado con IA" ni emojis de robots 🤖 en PRs, commits o comentarios.
- **Seguridad y Privacidad**: Cero secretos hardcodeados. Cero PII guardada en logs.

## 4. Protocolo Híbrido para Habilidades de Agentes (Determinismo + Validación Dinámica de IA)
Al ejecutar cualquier habilidad (ej. `sdd-init`, `sdd-verify`, `sdd-constitution`, `sdd-plan`), el agente DEBE cumplir 3 fases:
1. **Fase 1 (Determinística)**: Ejecutar herramientas CLI / scripts estáticos (`sdd ...`).
2. **Fase 2 (Auditoría Dinámica de IA)**: Inspeccionar el código fuente del repositorio.
3. **Fase 3 (Enriquecimiento Explícito)**: Inyectar las reglas y buenas prácticas descubiertas en `.specify/constitution/constitution.md`.
"""

    global_rules, _ = load_rules_catalog(str(td))
    if global_rules:
        sections = [r.content for r in global_rules if r.content.strip()]
        if sections:
            base_rules += "\n\n---\n\n" + "\n\n---\n\n".join(sections)

    const_content = read_constitution(str(td))
    if const_content:
        base_rules += f"\n\n---\n\n{const_content}\n"

    return base_rules


def prompt_select_agents(target_dir: str = ".") -> List[str]:
    print(f"\n{Color.BOLD}==> Selecciona los agentes de IA a configurar para SDD:{Color.RESET}")
    print("  1) Google Antigravity / Gemini 2.0 (AGY)  [.agents/, AGENTS.md]")
    print("  2) Claude Code                            [.claude/, CLAUDE.md]")
    print("  3) GitHub Copilot                         [.github/, copilot-instructions.md]")
    print("  4) Cursor IDE                             [.cursor/, .cursorrules]")
    print("  5) Windsurf                               [.windsurfrules]")
    print("  6) Gemini CLI                             [.gemini/, GEMINI.md]")
    print("  7) ChatGPT / Custom GPTs                  [CHATGPT.md]")
    print("  8) Todos los anteriores (All)")

    try:
        choice = input(f"\n{Color.BOLD}Ingresa los números separados por coma (ej: 1, 2) [Default: 1]: {Color.RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        choice = "1"

    if not choice:
        choice = "1"

    agent_map = {
        "1": "agy",
        "2": "claude",
        "3": "copilot",
        "4": "cursor",
        "5": "windsurf",
        "6": "gemini",
        "7": "chatgpt",
    }

    if "8" in choice.split(",") or "all" in choice.lower():
        return list(agent_map.values())

    selected = []
    for item in choice.split(","):
        k = item.strip()
        if k in agent_map:
            selected.append(agent_map[k])

    return selected or ["agy"]


def generate_adapters(
    target_dir: str = ".",
    gen_all: bool = False,
    claude: bool = False,
    copilot: bool = False,
    cursor: bool = False,
    gemini: bool = False,
    agy: bool = False,
    chatgpt: bool = False,
    windsurf: bool = False,
    interactive: bool = False,
) -> List[str]:
    td = Path(target_dir).resolve()
    td.mkdir(parents=True, exist_ok=True)
    generated_files: List[str] = []

    has_flags = any([gen_all, claude, copilot, cursor, gemini, agy, chatgpt, windsurf])
    if not has_flags:
        aj = td / ".specify" / "agents.json"
        if aj.exists():
            try:
                agents = json.loads(aj.read_text(encoding="utf-8")).get("selected_agents", [])
                agy = "agy" in agents
                gemini = "gemini" in agents
                claude = "claude" in agents
                copilot = "copilot" in agents
                cursor = "cursor" in agents
                chatgpt = "chatgpt" in agents
                windsurf = "windsurf" in agents
            except Exception:
                pass
        else:
            if interactive or (sys.stdin and sys.stdin.isatty()):
                selected = prompt_select_agents(target_dir=str(td))
            else:
                selected = detect_existing_agents(target_dir=str(td))
            agy = "agy" in selected
            gemini = "gemini" in selected
            claude = "claude" in selected
            copilot = "copilot" in selected
            cursor = "cursor" in selected
            chatgpt = "chatgpt" in selected
            windsurf = "windsurf" in selected

    if gen_all:
        claude = copilot = cursor = gemini = agy = chatgpt = windsurf = True

    active_agents = []
    if agy: active_agents.append("agy")
    if claude: active_agents.append("claude")
    if copilot: active_agents.append("copilot")
    if cursor: active_agents.append("cursor")
    if windsurf: active_agents.append("windsurf")
    if gemini: active_agents.append("gemini")
    if chatgpt: active_agents.append("chatgpt")

    specify_dir = td / ".specify"
    specify_dir.mkdir(parents=True, exist_ok=True)
    (specify_dir / "agents.json").write_text(json.dumps({"selected_agents": active_agents}, indent=2) + "\n", encoding="utf-8")

    global_rules, scoped_rules = load_rules_catalog(str(td))
    rules_text = get_sdd_core_rules(target_dir=str(td))
    log_info(f"Generando adaptadores Multi-IA SDD en: {td}")

    # 1. Claude Code
    if claude:
        (td / "CLAUDE.md").write_text(f"# Claude Code — Instrucciones SDD\n\n{rules_text}\n", encoding="utf-8")
        claude_dir = td / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{"command": "sdd hook pre-tool"}],
                "PostToolUse": [{"command": "sdd hook post-tool"}]
            }
        }, indent=2) + "\n", encoding="utf-8")
        
        # Generar reglas modulares en .claude/rules/
        claude_rules_dir = claude_dir / "rules"
        claude_rules_dir.mkdir(parents=True, exist_ok=True)
        for r in global_rules + scoped_rules:
            (claude_rules_dir / f"{r.name}.md").write_text(f"# {r.description}\n\n{r.content}\n", encoding="utf-8")
            generated_files.append(f".claude/rules/{r.name}.md")

        agents_dir = claude_dir / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "worker.json").write_text(json.dumps({"name": "worker", "description": "Worker Agent SDD"}, indent=2), encoding="utf-8")
        (agents_dir / "qa-reviewer.json").write_text(json.dumps({"name": "qa-reviewer", "description": "QA Reviewer Agent SDD"}, indent=2), encoding="utf-8")
        generated_files.extend(["CLAUDE.md", ".claude/settings.json", ".claude/agents/worker.json", ".claude/agents/qa-reviewer.json"])

    # 2. Antigravity 2.0 (AGY)
    if agy:
        (td / "AGENTS.md").write_text(f"# Google Antigravity (AGY) — Reglas del Sistema\n\n{rules_text}\n", encoding="utf-8")
        ad = td / ".agents"
        clean_agents_directory(ad)
        ar = ad / "rules"
        ask = ad / "skills"
        ar.mkdir(parents=True, exist_ok=True)
        ask.mkdir(parents=True, exist_ok=True)
        (ar / "sdd-rules.md").write_text(f"# Reglas SDD\n\n{rules_text}\n", encoding="utf-8")
        generated_files.extend(["AGENTS.md", ".agents/rules/sdd-rules.md"])

        # Generar cada regla modular en .agents/rules/
        for r in global_rules + scoped_rules:
            (ar / f"{r.name}.md").write_text(f"# {r.description}\n\n{r.content}\n", encoding="utf-8")
            generated_files.append(f".agents/rules/{r.name}.md")

        from sdd_engine.global_skills import get_canonical_skills_dir
        src_skills = get_canonical_skills_dir()
        if src_skills.exists() and src_skills.is_dir():
            for s_dir in sorted(src_skills.iterdir()):
                if s_dir.is_dir() and (s_dir / "SKILL.md").exists():
                    target_s = ask / s_dir.name
                    shutil.copytree(s_dir, target_s, dirs_exist_ok=True)
                    generated_files.append(f".agents/skills/{s_dir.name}/SKILL.md")

    # 3. GitHub Copilot
    if copilot:
        cd = td / ".github"
        pd = cd / "prompts"
        hd = cd / "hooks"
        pd.mkdir(parents=True, exist_ok=True)
        hd.mkdir(parents=True, exist_ok=True)
        (cd / "copilot-instructions.md").write_text(f"# GitHub Copilot — SDD\n\n{rules_text}\n", encoding="utf-8")
        for cmd in ["specify", "clarify", "plan", "checklist", "tasks", "analyze", "exec", "converge", "quick"]:
            (pd / f"speckit.{cmd}.prompt.md").write_text(f"---\ndescription: SDD phase /sdd-{cmd}\n---\nExecute SDD phase\n", encoding="utf-8")
            generated_files.append(f".github/prompts/speckit.{cmd}.prompt.md")
        (hd / "pre-tool.json").write_text(json.dumps({
            "name": "sdd-pre-tool-hook",
            "type": "pre-tool",
            "command": "sdd hook pre-tool",
            "description": "Pre-tool interceptor for security blocking and command verification"
        }, indent=2) + "\n", encoding="utf-8")
        (hd / "post-tool.json").write_text(json.dumps({
            "name": "sdd-post-tool-hook",
            "type": "post-tool",
            "command": "sdd hook post-tool",
            "description": "Post-tool interceptor for automated code verification"
        }, indent=2) + "\n", encoding="utf-8")

        generated_files.extend([".github/copilot-instructions.md", ".github/hooks/pre-tool.json", ".github/hooks/post-tool.json"])

    # 4. Cursor IDE (Reglas Modulares .mdc con frontmatter YAML)
    if cursor:
        (td / ".cursorrules").write_text(f"# Cursor AI Rules — SDD\n\n{rules_text}\n", encoding="utf-8")
        cursor_dir = td / ".cursor"
        rules_dir = cursor_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        
        # Regla maestra sdd-harness
        (rules_dir / "sdd-harness.mdc").write_text(f"---\ndescription: SDD Harness Rules\nglobs: *\nalwaysApply: true\n---\n\n{rules_text}\n", encoding="utf-8")
        generated_files.append(".cursor/rules/sdd-harness.mdc")

        # Reglas modulares .mdc respetando globs y alwaysApply
        for r in global_rules + scoped_rules:
            mdc_content = f"""---
description: {json.dumps(r.description)}
globs: {json.dumps(r.globs)}
alwaysApply: {str(r.always_apply).lower()}
---

{r.content}
"""
            (rules_dir / f"{r.name}.mdc").write_text(mdc_content, encoding="utf-8")
            generated_files.append(f".cursor/rules/{r.name}.mdc")

        (cursor_dir / "hooks.json").write_text(json.dumps({"hooks": {"pre-tool": "sdd hook pre-tool", "post-tool": "sdd hook post-tool"}}, indent=2), encoding="utf-8")
        generated_files.extend([".cursorrules", ".cursor/hooks.json"])

    # 5. Windsurf
    if windsurf:
        (td / ".windsurfrules").write_text(f"# Windsurf Cascade Rules — SDD\n\n{rules_text}\n", encoding="utf-8")
        ws_rules_dir = td / ".windsurf" / "rules"
        ws_rules_dir.mkdir(parents=True, exist_ok=True)
        for r in global_rules + scoped_rules:
            (ws_rules_dir / f"{r.name}.md").write_text(f"# {r.description}\n\n{r.content}\n", encoding="utf-8")
            generated_files.append(f".windsurf/rules/{r.name}.md")
        generated_files.append(".windsurfrules")

    # 6. Gemini CLI
    if gemini:
        gd = td / ".gemini"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "GEMINI.md").write_text(f"# Gemini CLI — SDD Context & Rules\n\n{rules_text}\n", encoding="utf-8")
        generated_files.append(".gemini/GEMINI.md")

    # 7. ChatGPT
    if chatgpt:
        (td / "CHATGPT.md").write_text(f"# ChatGPT Custom Prompt — SDD\n\n{rules_text}\n", encoding="utf-8")
        generated_files.append("CHATGPT.md")

    log_success("Adaptadores Multi-IA SDD generados correctamente.")
    return generated_files
