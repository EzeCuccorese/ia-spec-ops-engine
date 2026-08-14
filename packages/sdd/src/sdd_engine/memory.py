"""
sdd_engine.memory — Memoria de proyecto y registro de eventos para SDD.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Optional, Union

from sdd_engine.utils import find_project_root
from sdd_engine.exceptions import SDDMemoryError



def get_project_dir(d: Union[str, Path] = ".") -> Path:
    p = Path(d).resolve()
    if p.is_dir():
        return find_project_root(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def init(target_dir: Union[str, Path] = ".") -> None:
    td = get_project_dir(target_dir)
    sd = td / ".specify"
    (sd / "history").mkdir(parents=True, exist_ok=True)
    (sd / "specs").mkdir(parents=True, exist_ok=True)
    mf = sd / "memory.md"
    if not mf.exists():
        content = """# SDD Project Memory & Context

This file stores key architectural decisions, conventions, learned patterns, and active context for Specification-Driven Development (SDD).

## 1. Project Patterns & Architecture
- **Methodology**: Spec-Driven Development (SDD)
- **Worktree Isolation**: All feature execution and docs generation run in isolated Git Worktrees.
- **Verification**: Strict verification required before completing tasks.

## 2. Key Decisions & Conventions
- Maintain backward compatibility across component updates.
- Keep module interfaces decoupled and documented.

## 3. 🔍 Descubrimientos Dinámicos de IA & Buenas Prácticas Detectadas
*(Espacio reservado para que el agente IA documente patrones detectados dinámicamente en el repositorio: stack, linters, arquitectura, tests y convenciones no escritas)*

## 4. Consolidated Execution History

| Timestamp | Type | Title | Status |
|-----------|------|-------|--------|
"""
        mf.write_text(content, encoding="utf-8")
        print(f"Initialized SDD memory structure at {sd}")
    else:
        print(f"SDD memory structure already exists at {sd}")


def log(
    title: str,
    event_type: str = "exec",
    details: str = "",
    status: str = "SUCCESS",
    target_dir: Union[str, Path] = ".",
) -> Path:
    td = get_project_dir(target_dir)
    init(target_dir)
    sd = td / ".specify"
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%d-%H%M%S")
    iso_date = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "event"
    hf = sd / "history" / f"{ts_str}-{slug}.md"
    hf.write_text(
        f"# History Record: {title}\n\n- **Timestamp:** {iso_date}\n- **Type:** {event_type}\n- **Status:** {status}\n\n## Description & Details\n{details}\n",
        encoding="utf-8",
    )
    mf = sd / "memory.md"
    if mf.exists():
        with open(mf, "a", encoding="utf-8") as f:
            f.write(f"| {iso_date} | {event_type} | {title} | {status} |\n")
    print(f"Logged SDD event to {hf}")
    return hf


def log_task_event(
    task_id: str,
    role: str,
    title: str,
    details: str = "",
    status: str = "SUCCESS",
    target_dir: Union[str, Path] = ".",
) -> Path:
    td = get_project_dir(target_dir)
    init(target_dir)
    sd = td / ".specify"
    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%d-%H%M%S")
    iso_date = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{task_id}-{role}-{title}".lower()).strip("-") or "task-event"
    hf = sd / "history" / f"{ts_str}-{slug}.md"

    content = f"""# Task Execution History: {title}

- **Task ID:** {task_id}
- **Role:** {role}
- **Timestamp:** {iso_date}
- **Status:** {status}

## Summary & Details
{details}
"""
    hf.write_text(content, encoding="utf-8")

    mf = sd / "memory.md"
    if mf.exists():
        with open(mf, "a", encoding="utf-8") as f:
            f.write(f"| {iso_date} | {role}:{task_id} | {title} | {status} |\n")
    print(f"Logged SDD task event ({role}) to {hf}")
    return hf


def read(target_dir: Union[str, Path] = ".") -> str:
    td = get_project_dir(target_dir)
    mf = td / ".specify" / "memory.md"
    if mf.exists():
        content = mf.read_text(encoding="utf-8")
        print(content)
        return content
    else:
        raise SDDMemoryError(f"No .specify/memory.md found in {td}. Run 'sdd init' first.")


def consolidate(target_dir: Union[str, Path] = ".") -> None:
    td = get_project_dir(target_dir)
    sd = td / ".specify"
    hd = sd / "history"
    if not hd.exists():
        raise SDDMemoryError(f"No .specify/history directory found in {td}.")
    md_files = sorted(hd.glob("*.md"), reverse=True)
    print(f"Consolidating {len(md_files)} history records into {sd / 'memory.md'}...")
    entries: list[str] = []
    for f in md_files:
        content = f.read_text(errors="ignore")
        ts = re.search(r"\*\*Timestamp:\*\*\s*(.+)", content)
        typ = re.search(r"\*\*Type:\*\*\s*(.+)", content)
        sts = re.search(r"\*\*Status:\*\*\s*(.+)", content)
        tit = re.search(r"# History Record:\s*(.+)", content)
        entries.append(
            f"| {ts.group(1).strip() if ts else 'Unknown'} | {typ.group(1).strip() if typ else 'exec'} | {tit.group(1).strip() if tit else f.name} | {sts.group(1).strip() if sts else 'SUCCESS'} |"
        )
    base = """# SDD Project Memory & Context

This file stores key architectural decisions, conventions, learned patterns, and active context for Specification-Driven Development (SDD).

## 1. Project Patterns & Architecture
- **Methodology**: Spec-Driven Development (SDD)
- **Worktree Isolation**: All feature execution and docs generation run in isolated Git Worktrees.
- **Verification**: Strict verification required before completing tasks.

## 2. Key Decisions & Conventions
- Maintain backward compatibility across component updates.
- Keep module interfaces decoupled and documented.

## 3. Consolidated Execution History

| Timestamp | Type | Title | Status |
|-----------|------|-------|--------|
"""
    (sd / "memory.md").write_text(base + "\n".join(entries) + "\n", encoding="utf-8")
    print(f"Memory consolidated successfully with {len(entries)} entries.")
