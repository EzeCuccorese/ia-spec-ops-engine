"""
devscripts_common — Paquete base de utilidades y librerías compartidas para Devscripts.
"""

from __future__ import annotations

from devscripts_common.colors import (
    Color,
    RED,
    GREEN,
    YELLOW,
    BLUE,
    MAGENTA,
    CYAN,
    WHITE,
    GRAY,
    BOLD,
    DIM,
    UNDERLINE,
    RESET,
    END,
    console,
    err_console,
    colorize,
    log_info,
    log_success,
    log_warning,
    log_error,
)
from devscripts_common.dotenv import parse_dotenv
from devscripts_common.frontmatter import parse_frontmatter
from devscripts_common.project import (
    ProjectType,
    find_project_root,
    detect_project_type,
    read_package_json,
    is_spring_boot_app,
    is_go_service,
    is_rust_service,
    detect_fe_framework,
)
from devscripts_common.subprocess import (
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
