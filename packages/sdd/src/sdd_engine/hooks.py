"""
devscripts.sdd.hooks — Spec-Driven Development Deterministic Tool Hooks.

Provides pre-tool security interception (blocking dangerous commands, root deletion,
curl|sh remote execution, fork bombs, unauthorized DB writes) and post-tool automated verification.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union, Set

from sdd_engine.utils import log_info, log_success, log_warning, log_error
from sdd_engine.verify import run_verification
from sdd_engine.invariants import VerificationPayload


# Set of edit tool names that represent file modification actions
EDIT_TOOLS: Set[str] = {
    "write",
    "edit",
    "replace",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "save",
    "patch",
    "apply_patch",
}

# Regex patterns for pre-tool security blocking
DANGEROUS_COMMAND_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "Root/Home Directory Deletion (rm -rf /)",
        re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+([/]|/\*|~|\$HOME)(\s+|$)", re.IGNORECASE),
    ),
    (
        "Root/Home Directory Deletion (rm -r -f /)",
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+-[a-zA-Z]*f[a-zA-Z]*\s+([/]|/\*|~|\$HOME)(\s+|$)", re.IGNORECASE),
    ),
    (
        "Unsafe Remote Script Execution (curl|sh / wget|sh)",
        re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash|zsh|dash)", re.IGNORECASE),
    ),
    (
        "Fork Bomb Pattern",
        re.compile(r":\(\)\{\s*:\|:&\s*\};:", re.IGNORECASE),
    ),
    (
        "Disk Overwrite / Raw Block Device Mutation",
        re.compile(r"\b(mkfs|dd\s+if=.*of=/dev/)\b", re.IGNORECASE),
    ),
    (
        "Destructive Database Drop",
        re.compile(r"\bDROP\s+(DATABASE|SCHEMA)\b", re.IGNORECASE),
    ),
]

DB_WRITE_MUTATION_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("TRUNCATE TABLE", re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE)),
    ("DELETE FROM", re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)),
    ("INSERT INTO", re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)),
    ("UPDATE SET", re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE)),
    ("ALTER TABLE", re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE)),
    ("CREATE TABLE", re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE)),
]


def extract_command_string(tool_args: Union[Dict[str, Any], str, None]) -> str:
    """
    Extract text/command representation from tool arguments.
    """
    if tool_args is None:
        return ""
    if isinstance(tool_args, str):
        return tool_args
    if isinstance(tool_args, dict):
        for key in ("CommandLine", "command", "cmd", "script", "query", "sql", "code", "input"):
            val = tool_args.get(key)
            if isinstance(val, str) and val.strip():
                return val
        str_vals = [str(v) for v in tool_args.values() if isinstance(v, (str, int, float))]
        return " ".join(str_vals)
    return str(tool_args)


def extract_modified_files(tool_args: Union[Dict[str, Any], str, None]) -> Optional[List[str]]:
    """
    Extract file paths modified by tool action if specified in tool_args.
    """
    if isinstance(tool_args, dict):
        for key in ("TargetFile", "target_file", "file", "path", "filename", "filepath"):
            val = tool_args.get(key)
            if isinstance(val, str) and val.strip():
                return [val.strip()]
        if "files" in tool_args and isinstance(tool_args["files"], list):
            return [str(f) for f in tool_args["files"] if isinstance(f, str)]
    elif isinstance(tool_args, str):
        p = Path(tool_args.strip())
        if p.suffix and ("/" in tool_args or "\\" in tool_args or "." in tool_args):
            return [tool_args.strip()]
    return None


def handle_pre_tool_event(
    tool_name: str,
    tool_args: Union[Dict[str, Any], str, None] = None,
    db_write_authorized: bool = False,
) -> Tuple[bool, str]:
    """
    Intercept tools or commands prior to execution to enforce safety policies.

    Blocks:
    - Dangerous system commands (rm -rf /, curl|sh, fork bomb, disk format, DROP DATABASE)
    - Unauthorized DB write operations (INSERT, UPDATE, DELETE, DROP TABLE) unless explicit authorization is granted.

    Returns:
    (approved: bool, reason: str)
    """
    cmd_str = extract_command_string(tool_args)

    # 1. Check general dangerous command patterns
    for pattern_name, pattern_re in DANGEROUS_COMMAND_PATTERNS:
        if pattern_re.search(cmd_str):
            reason = f"Blocked dangerous operation: {pattern_name}"
            log_warning(f"[PRE-TOOL HOOK] {reason} (tool: {tool_name})")
            return (False, reason)

    # 2. Check DB write operations authorization
    is_db_tool = tool_name.lower() in ("db", "sql", "db_execute", "database", "db_query")
    has_db_mutation = False
    mutation_type = ""

    for mut_name, mut_re in DB_WRITE_MUTATION_PATTERNS:
        if mut_re.search(cmd_str):
            has_db_mutation = True
            mutation_type = mut_name
            break

    if (is_db_tool or has_db_mutation) and has_db_mutation and not db_write_authorized:
        reason = f"Blocked unauthorized DB write operation: {mutation_type}"
        log_warning(f"[PRE-TOOL HOOK] {reason} (tool: {tool_name})")
        return (False, reason)

    log_info(f"[PRE-TOOL HOOK] Approved execution for tool '{tool_name}'")
    return (True, "Approved")


def handle_post_tool_event(
    tool_name: str,
    tool_args: Union[Dict[str, Any], str, None] = None,
    target_dir: str = ".",
    as_payload: bool = False,
    **verification_kwargs: Any,
) -> Union[Dict[str, Any], VerificationPayload]:
    """
    Intercept post-tool execution events (write, edit, replace, etc.) and run rapid automated verification.

    Invokes `devscripts.sdd.verify.run_verification()`.

    Returns:
    VerificationPayload dictionary (or VerificationPayload object if as_payload=True).
    """
    modified_files = extract_modified_files(tool_args)
    log_info(f"[POST-TOOL HOOK] Running automated verification after tool '{tool_name}'")

    payload: VerificationPayload = run_verification(
        target_dir=target_dir,
        modified_files=modified_files,
        **verification_kwargs,
    )

    if payload.passed:
        log_success("[POST-TOOL HOOK] Automated verification PASSED")
    else:
        log_warning(f"[POST-TOOL HOOK] Automated verification FAILED: {payload.remediation_instructions}")

    if as_payload:
        return payload
    return payload.to_dict()
