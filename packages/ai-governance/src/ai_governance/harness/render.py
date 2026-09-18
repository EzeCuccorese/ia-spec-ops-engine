"""Renders the self-wiring documentation block injected into AGENTS.md."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..rules.core.catalog import ToolDefinition
from ..rules.core.hosts import HostBinding

HEADER = "## Harness Wiring (self-configure; no installer)"

INTRO = (
    "For each tool below with an automatic trigger: if your runtime supports that "
    "event, register the command there (see host map). If it does not, run the "
    "command manually at that point in your workflow. This block is managed by "
    "`governance harness install`; re-run it to refresh, never duplicate it. "
    "Verify with `governance doctor`."
)

AGENT_MODE_TEXT = (
    "Set `SPECOPS_AGENT=1` in the environment your agent uses to run shell "
    "commands, or rely on non-TTY detection. Output stays under ~20 lines / 1500 "
    "chars; use `--full` or `--json` only when needed."
)


def render_wiring_block(
    tools: Sequence[ToolDefinition],
    host_bindings_by_host: Mapping[str, Sequence[HostBinding]],
) -> str:
    """Renders the harness wiring markdown block for injection into AGENTS.md."""
    automatic = [t for t in tools if t.trigger != "on-demand"]

    lines = [
        HEADER,
        "",
        INTRO,
        "",
        "### Automatic tools",
        "| Trigger | Command | Fail mode | Notes |",
        "|---|---|---|---|",
    ]
    for tool in automatic:
        lines.append(f"| {tool.trigger} | `{tool.command}` | {tool.fail_mode} | {tool.purpose} |")

    lines.extend(["", "### Host map"])
    for host, bindings in host_bindings_by_host.items():
        lines.append(f"#### {host}")
        lines.append("| Trigger | Location | Notes |")
        lines.append("|---|---|---|")
        for binding in bindings:
            lines.append(f"| {binding.trigger} | {binding.location} | {binding.notes} |")
        lines.append("")

    lines.extend(
        [
            "### Agent mode",
            AGENT_MODE_TEXT,
        ]
    )

    return "\n".join(lines).rstrip() + "\n"
