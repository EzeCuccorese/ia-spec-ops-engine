"""
devscripts_common — Paquete base de utilidades y librerías compartidas para Devscripts.
"""

from __future__ import annotations

from workspace_engine.common.colors import (
    BLUE,
    BOLD,
    CYAN,
    DIM,
    END,
    GRAY,
    GREEN,
    MAGENTA,
    RED,
    RESET,
    UNDERLINE,
    WHITE,
    YELLOW,
    Color,
    colorize,
    console,
    err_console,
    log_error,
    log_info,
    log_success,
    log_warning,
)
from workspace_engine.common.dotenv import parse_dotenv
from workspace_engine.common.frontmatter import parse_frontmatter
from workspace_engine.common.project import (
    ProjectType,
    detect_fe_framework,
    detect_project_type,
    find_project_root,
    is_go_service,
    is_rust_service,
    is_spring_boot_app,
    read_package_json,
)
from workspace_engine.common.subprocess import (
    DEFAULT_COMMAND_TIMEOUT,
    run_command,
    run_command_safe,
)

__all__ = [
    "Color",
    "RED",
    "GREEN",
    "YELLOW",
    "BLUE",
    "MAGENTA",
    "CYAN",
    "WHITE",
    "GRAY",
    "BOLD",
    "DIM",
    "UNDERLINE",
    "RESET",
    "END",
    "console",
    "err_console",
    "colorize",
    "log_info",
    "log_success",
    "log_warning",
    "log_error",
    "parse_dotenv",
    "parse_frontmatter",
    "ProjectType",
    "find_project_root",
    "detect_project_type",
    "read_package_json",
    "is_spring_boot_app",
    "is_go_service",
    "is_rust_service",
    "detect_fe_framework",
    "DEFAULT_COMMAND_TIMEOUT",
    "run_command",
    "run_command_safe",
]
