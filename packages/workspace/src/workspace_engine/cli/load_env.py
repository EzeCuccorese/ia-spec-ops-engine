#!/usr/bin/env python3
"""
workspace_engine.cli.load_env — Actualización determinista de variables de entorno en archivos de configuración YAML/dotenv.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List

from workspace_engine.utils import find_project_root, log_error, log_info, log_success, log_warning


def update_env_in_yaml(yaml_path: Path, services: List[str], key: str, value: str) -> bool:
    if not yaml_path.is_file():
        log_error(f"Archivo no encontrado: {yaml_path}")
        return False

    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 4096

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)

        updated = False
        for app in data.get("apps", []):
            if app.get("name") in services:
                if "configMapProperties" not in app or app["configMapProperties"] is None:
                    app["configMapProperties"] = {}
                if app["configMapProperties"].get(key) != value:
                    app["configMapProperties"][key] = value
                    updated = True
                    log_success(f"  Actualizado {app['name']}")

        if updated:
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f)
            log_success(f"  Guardado en {yaml_path}")
            return True
        else:
            log_info("  Sin cambios requeridos.")
            return True
    except Exception as e:
        log_error(f"Error procesando YAML {yaml_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Actualiza variables en archivos YAML de GitOps o despliegue.")
    parser.add_argument("--envs", required=True, help="Ambientes (separados por coma)")
    parser.add_argument("--services", required=True, help="Servicios (separados por coma)")
    parser.add_argument("--var", required=True, help="Nombre de la variable")
    parser.add_argument("--values", required=True, help="Valores (separados por coma)")
    parser.add_argument("--root", default=os.path.expanduser("~/projects/gitops/apps/apps"), help="Directorio raíz")
    parser.add_argument("--suffix", help="Sufijo opcional para valores")
    args = parser.parse_args()

    envs = [e.strip() for e in args.envs.split(",")]
    services = [s.strip() for s in args.services.split(",")]
    values = [v.strip() for v in args.values.split(",")]
    key = args.var.strip()
    root_dir = Path(args.root)

    if args.suffix:
        values = [f"{v}{args.suffix}" for v in values]

    env_to_value = {envs[i]: values[i] for i in range(min(len(envs), len(values)))}

    for env in envs:
        yaml_path = root_dir / f"values.{env}.yaml"
        if env not in env_to_value:
            continue
        log_info(f"Procesando ambiente {env}...")
        update_env_in_yaml(yaml_path, services, key, env_to_value[env])


if __name__ == "__main__":
    main()
