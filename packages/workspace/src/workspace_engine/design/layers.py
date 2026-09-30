"""
workspace_engine.design.layers — Architecture layer-boundary check for ``ws design``.

Runs only when the ai-governance ``architecture`` profile is enabled (top-level
``profiles = [...]`` in ``.ai-governance/config.toml``) and ``[design.layers]`` is
configured. A deterministic, no-external-tools import scanner per language (priority
Java, JS/TS, Python, Go, then Kotlin, C#, PHP, Rust, Dart) resolves each import to a
repo-relative pseudo-path and flags an inner layer importing an outer one.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath

from .config import LayersConfig
from .metrics import Violation

_JAVA_IMPORT = re.compile(r"^\s*import\s+(static\s+)?([\w.]+?)(\.\*)?\s*;?\s*$")
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+)")
_PY_FROM_IMPORT = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\b")
_CS_USING = re.compile(r"^\s*using\s+(?!static\s)([\w.]+)\s*;")
_PHP_USE = re.compile(r"^\s*use\s+\\?([\w\\]+?)(?:\s+as\s+\w+)?\s*;")
_RUST_USE = re.compile(r"^\s*use\s+crate::([\w:]+)")
_JS_SPEC = re.compile(r"""(?:from|require\(|import\()\s*['"]([^'"]+)['"]""")
_GO_QUOTED = re.compile(r'"([^"]+)"')
_DART_PACKAGE = re.compile(r"""^\s*import\s+['"]package:([^'"]+)['"]""")
_DART_RELATIVE = re.compile(r"""^\s*import\s+['"](\.[^'"]+)['"]""")


@dataclass(frozen=True)
class Import:
    line: int
    raw: str
    module: str  # repo-relative pseudo-path, slash-separated; empty if not resolvable


def _strip_comments(source: str, style: str) -> list[str]:
    """Blanks out comments so commented-out imports never match, line-aligned."""
    if style == "hash":
        return [re.sub(r"#.*$", "", line) for line in source.splitlines()]
    # C-style: strip // line comments and /* */ block comments (line-aligned).
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return [re.sub(r"//.*$", "", line) for line in without_block.splitlines()]


def _java_kotlin(lines: list[str]) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _JAVA_IMPORT.match(line)
        if match:
            dotted = match.group(2)
            result.append(Import(i, dotted, dotted.replace(".", "/")))
    return result


def _resolve_relative(file_dir: str, specifier: str) -> str:
    joined = normpath(f"{file_dir}/{specifier}") if file_dir else normpath(specifier)
    return joined.lstrip("./")


def _strip_known_ext(path: str) -> str:
    for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if path.endswith(ext):
            return path[: -len(ext)]
    return path


def _js_ts(lines: list[str], file_dir: str) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        for match in _JS_SPEC.finditer(line):
            specifier = match.group(1)
            if not specifier.startswith("."):
                continue  # bare (package) specifiers are ignored
            resolved = _strip_known_ext(_resolve_relative(file_dir, specifier))
            result.append(Import(i, specifier, resolved))
    return result


def _python(lines: list[str], package_dir: str) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _PY_IMPORT.match(line)
        if match:
            dotted = match.group(1)
            result.append(Import(i, dotted, dotted.replace(".", "/")))
            continue
        match = _PY_FROM_IMPORT.match(line)
        if not match:
            continue
        dots, dotted = match.group(1), match.group(2)
        raw = f"{dots}{dotted}"
        if not dots:
            result.append(Import(i, raw, dotted.replace(".", "/")))
            continue
        base_parts = package_dir.split("/") if package_dir else []
        up = len(dots) - 1
        base_parts = base_parts[: len(base_parts) - up] if up else base_parts
        if dotted:
            base_parts = base_parts + dotted.split(".")
        result.append(Import(i, raw, "/".join(p for p in base_parts if p)))
    return result


def _go(lines: list[str], module: str | None) -> list[Import]:
    result = []
    in_block = False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("import ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        if in_block or stripped.startswith("import "):
            match = _GO_QUOTED.search(line)
            if not match:
                continue
            path = match.group(1)
            if module and path.startswith(module + "/"):
                path = path[len(module) + 1 :]
            elif module and path == module:
                path = ""
            result.append(Import(i, match.group(1), path))
    return result


def _csharp(lines: list[str]) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _CS_USING.match(line)
        if match:
            result.append(Import(i, match.group(1), match.group(1).replace(".", "/")))
    return result


def _php(lines: list[str]) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _PHP_USE.match(line)
        if match:
            result.append(Import(i, match.group(1), match.group(1).replace("\\", "/")))
    return result


def _rust(lines: list[str]) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _RUST_USE.match(line)
        if match:
            path = match.group(1).split(" as ")[0].rstrip(";")
            result.append(Import(i, f"crate::{match.group(1)}", path.replace("::", "/")))
    return result


def _dart(lines: list[str], file_dir: str) -> list[Import]:
    result = []
    for i, line in enumerate(lines, start=1):
        match = _DART_PACKAGE.match(line)
        if match:
            target = match.group(1)
            if target.endswith(".dart"):
                target = target[: -len(".dart")]
            result.append(Import(i, target, target.split("/", 1)[-1]))
            continue
        match = _DART_RELATIVE.match(line)
        if match:
            resolved = _resolve_relative(file_dir, match.group(1))
            if resolved.endswith(".dart"):
                resolved = resolved[: -len(".dart")]
            result.append(Import(i, match.group(1), resolved))
    return result


_EXT_STYLE = {
    "java": "c",
    "kt": "c",
    "kts": "c",
    "ts": "c",
    "tsx": "c",
    "js": "c",
    "jsx": "c",
    "mjs": "c",
    "cjs": "c",
    "go": "c",
    "cs": "c",
    "php": "c",
    "rs": "c",
    "dart": "c",
    "py": "hash",
}


def extract_imports(
    relative: str, extension: str, source: str, go_module: str | None
) -> list[Import]:
    """Parses ``source`` (already comment-stripped) into repo-relative pseudo-imports."""
    style = _EXT_STYLE.get(extension)
    if style is None:
        return []
    lines = _strip_comments(source, style)
    file_dir = str(Path(relative).parent.as_posix())
    if file_dir == ".":
        file_dir = ""
    if extension in ("java", "kt", "kts"):
        return _java_kotlin(lines)
    if extension in ("ts", "tsx", "js", "jsx", "mjs", "cjs"):
        return _js_ts(lines, file_dir)
    if extension == "py":
        return _python(lines, file_dir)
    if extension == "go":
        return _go(lines, go_module)
    if extension == "cs":
        return _csharp(lines)
    if extension == "php":
        return _php(lines)
    if extension == "rs":
        return _rust(lines)
    if extension == "dart":
        return _dart(lines, file_dir)
    return []


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = f"/{path}"
    return any(fnmatch.fnmatch(candidate, pattern) for pattern in patterns)


def layer_of(path: str, config: LayersConfig) -> str | None:
    """The first configured layer (in ``order``) whose globs match ``path``, if any."""
    for layer in config.order:
        globs = config.globs_for(layer)
        if _matches(path, globs) or _matches(f"{path}/x", globs):
            return layer
    return None


def go_module_name(root: Path) -> str | None:
    go_mod = root / "go.mod"
    if not go_mod.is_file():
        return None
    for line in go_mod.read_text(encoding="utf-8").splitlines():
        if line.startswith("module "):
            return line.removeprefix("module ").strip()
    return None


def _touches(changed: dict[str, set[int] | None] | None, path: str, line: int) -> bool:
    if changed is None or path not in changed:
        return False
    entry = changed[path]
    return entry is None or line in entry


def violations_for_file(
    root: Path,
    path: Path,
    config: LayersConfig,
    go_module: str | None,
    changed: dict[str, set[int] | None] | None = None,
) -> list[Violation]:
    relative = path.resolve().relative_to(root).as_posix()
    file_layer = layer_of(relative, config)
    if file_layer is None:
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    extension = path.suffix.lstrip(".")
    file_index = config.order.index(file_layer)
    violations: list[Violation] = []
    for imp in extract_imports(relative, extension, source, go_module):
        if not imp.module:
            continue
        import_layer = layer_of(imp.module, config)
        if import_layer is None:
            continue
        import_index = config.order.index(import_layer)
        if import_index < file_index:
            origin = "new" if _touches(changed, relative, imp.line) else "legacy"
            violations.append(
                Violation(
                    path=relative,
                    symbol=f"{file_layer} → {import_layer} ({imp.raw})",
                    start_line=imp.line,
                    end_line=imp.line,
                    metric="layers",
                    value=1,
                    limit=0,
                    origin=origin,
                )
            )
    return violations


def layer_violations(
    root: Path,
    paths: list[Path],
    config: LayersConfig,
    changed: dict[str, set[int] | None] | None = None,
) -> list[Violation]:
    """Layer-boundary violations across ``paths`` (files, resolved) under ``root``."""
    go_module = go_module_name(root)
    violations: list[Violation] = []
    for path in paths:
        if not path.is_file() or path.suffix.lstrip(".") not in _EXT_STYLE:
            continue
        violations.extend(violations_for_file(root, path, config, go_module, changed))
    violations.sort(key=lambda v: (v.path, v.start_line))
    return violations
