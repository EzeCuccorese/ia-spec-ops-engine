#!/usr/bin/env python3
"""
workspace_engine.cli.init_env — Sincronización e inicialización interactiva de variables .env a partir de plantillas .env.example.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from workspace_engine.utils import Color, find_project_root, log_error, log_info, log_success, log_warning, parse_dotenv


def parse_example_file(example_path: Path) -> List[Tuple[str, str, str]]:
    """Devuelve una lista de tuplas (comentario, variable, default_value)."""
    results: List[Tuple[str, str, str]] = []
    if not example_path.is_file():
        return results

    current_comment = ""
    for line in example_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if stripped:
                current_comment = f"{current_comment} — {stripped}" if current_comment else stripped
        elif "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            results.append((current_comment, k.strip(), v.strip().strip('"').strip("'")))
            current_comment = ""
        else:
            current_comment = ""
    return results


def sync_env_file(example_path: Path, target_path: Path, force: bool = False, check_only: bool = False) -> int:
    if not example_path.is_file():
        log_error(f"Archivo de plantilla no encontrado: {example_path}")
        return 1

    existing_values: Dict[str, str] = parse_dotenv(target_path) if target_path.is_file() else {}
    example_items = parse_example_file(example_path)

    missing: List[Tuple[str, str, str]] = []
    for comment, var, default_val in example_items:
        if var not in existing_values or not existing_values[var]:
            missing.append((comment, var, default_val))

    if check_only:
        if missing:
            print(f"\n{Color.YELLOW}⚠ Variables no configuradas en {target_path}:{Color.RESET}")
            for comment, var, default_val in missing:
                hint = f"={Color.DIM}{default_val}{Color.RESET}" if default_val else ""
                print(f"  {Color.YELLOW}•{Color.RESET} {var}{hint}")
            return 1
        else:
            log_success(f"{target_path} está completamente configurado.")
            return 0

    if not target_path.is_file():
        shutil.copy2(example_path, target_path)
        log_info(f"Creado {target_path} a partir de plantilla.")

    print(f"\n{Color.BOLD}Configurar variables de entorno:{Color.RESET} {target_path.name}\n")
    updated = dict(existing_values)

    for comment, var, default_val in example_items:
        current_val = existing_values.get(var, "")
        if not force and current_val:
            continue

        if comment:
            print(f"  {Color.DIM}# {comment}{Color.RESET}")
        prompt_val = current_val or default_val
        if prompt_val:
            print(f"  {Color.YELLOW}💡 Valor actual / default: {prompt_val}{Color.RESET}")
        
        user_input = input(f"  {Color.BOLD}{var}:{Color.RESET} [{prompt_val}]: ").strip()
        final_val = user_input if user_input else prompt_val
        updated[var] = final_val
        print("")

    # Escribir archivo actualizado
    lines = [f"# Generado por init-env"]
    for comment, var, _ in example_items:
        val = updated.get(var, "")
        if "\n" in val:
            lines.append(f'{var}="{val}"')
        else:
            lines.append(f"{var}={val}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_success(f"Archivo {target_path} guardado correctamente.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Inicializa o sincroniza variables en config/.env")
    parser.add_argument("--force", action="store_true", help="Preguntar por todas las variables, no solo las faltantes")
    parser.add_argument("--check-only", action="store_true", help="Solo verificar si faltan variables")
    args = parser.parse_args()

    root = find_project_root()
    env_example = root / "config" / ".env.example"
    env_file = root / "config" / ".env"

    if not env_example.is_file():
        # Intentar en templates/
        env_example = root / "templates" / "config" / ".env.example"

    sys.exit(sync_env_file(env_example, env_file, force=args.force, check_only=args.check_only))


if __name__ == "__main__":
    main()
