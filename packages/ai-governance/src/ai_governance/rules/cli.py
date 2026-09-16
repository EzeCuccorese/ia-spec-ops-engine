from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agents import ALL_ADAPTERS, filter_rules_by_tech
from .core.catalog import RuleCatalog, RuleDefinition
from .core.storage import RuleStorage
from .core.tui import select_multiple, select_one

console = Console()


def show_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🛠️  SPECOPS RULES[/bold cyan] — [white]Software Engineering Standards & Multi-Agent Harness[/white]",
            border_style="cyan",
        )
    )


def list_catalog(catalog: RuleCatalog) -> None:
    table = Table(title="📚 Canonical Engineering Rules Catalog", border_style="cyan")
    table.add_column("ID", style="bold green")
    table.add_column("Category", style="yellow")
    table.add_column("Description", style="white")
    table.add_column("Globs / Triggers", style="dim cyan")

    for rule in catalog.rules:
        table.add_row(
            rule.id,
            rule.category,
            rule.description,
            ", ".join(rule.globs[:3]) + ("..." if len(rule.globs) > 3 else ""),
        )
    console.print(table)


def run_interactive_installer(catalog: RuleCatalog, root: Path) -> None:
    show_banner()

    # 1. Scope selection
    scope_idx = select_one(
        "Select target installation scope:",
        [
            "🌐 Global (Machine-wide in ~/.specops/rules/ for all projects)",
            "📁 Local (Project-local in .specops/rules/)",
        ],
        default_index=0,
    )
    is_global = scope_idx == 0
    storage = RuleStorage.global_storage() if is_global else RuleStorage.local_storage(root)

    # 2. Agent selection
    agent_options = [(aid, adapter.display_name) for aid, adapter in ALL_ADAPTERS.items()]
    selected_agent_ids = select_multiple(
        "Select AI coding agents to configure:",
        agent_options,
        default_checked=[aid for aid, _ in agent_options],
    )
    selected_adapters = [ALL_ADAPTERS[aid] for aid in selected_agent_ids if aid in ALL_ADAPTERS]

    # 3. Rule category / stacks selection
    category_options = [
        ("all", "✨ Select ALL 28 Rules (Full Enterprise Suite)"),
        (
            "1-core",
            "🏛️  Core Rules (Clean Code, SOLID, DDD, Clean Architecture, Testing, Security, EDA)",
        ),
        ("2-stacks", "💻 Language Stacks (Python, React, Java, C#, Go, Rust, Kotlin, PHP, Dart)"),
        (
            "3-infrastructure",
            "☁️  Infrastructure & DB (Migrations, SQL, Docker, K8s, CI/CD, APIs, Observability)",
        ),
        ("4-docs", "📐 Documentation & Diagrams (C4 Architecture Model, Mermaid, ADRs)"),
    ]
    selected_cats = select_multiple(
        "Select Rule Categories to install:",
        category_options,
        default_checked=["all"],
    )

    chosen_rules: list[RuleDefinition] = []
    by_cat = catalog.by_category()

    if "all" in selected_cats:
        chosen_rules = catalog.rules
    else:
        for cat_id in selected_cats:
            chosen_rules.extend(by_cat.get(cat_id, []))

    if not chosen_rules:
        chosen_rules = catalog.rules

    # Save to storage
    saved_path = storage.save_rules(chosen_rules)
    console.print(
        f"[bold green]✔[/bold green] Saved [bold]{len(chosen_rules)} rules[/bold] to [cyan]{saved_path}[/cyan]"
    )

    # Install into selected adapters
    for adapter in selected_adapters:
        target = adapter.install(chosen_rules, saved_path, root, is_global)
        console.print(
            f"[bold green]✔[/bold green] Configured {adapter.display_name}: [cyan]{target}[/cyan]"
        )

    console.print("\n[bold green]🎉 Rules installation completed successfully![/bold green]\n")


def run_uninstaller(root: Path) -> None:
    show_banner()
    scope_idx = select_one(
        "Select scope to uninstall:",
        [
            "🌐 Global (~/)",
            "📁 Local (Current Project)",
        ],
        default_index=0,
    )
    is_global = scope_idx == 0

    storage = RuleStorage.global_storage() if is_global else RuleStorage.local_storage(root)
    storage.delete_owned()

    for adapter in ALL_ADAPTERS.values():
        res = adapter.uninstall(root, is_global)
        if res:
            console.print(
                f"[bold green]✔[/bold green] Cleaned {adapter.display_name}: [cyan]{res}[/cyan]"
            )

    console.print(
        "\n[bold green]✨ All rules successfully uninstalled and user files preserved.[/bold green]\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="rules", description="SpecOps Rules — Software Engineering Standards TUI"
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["install", "uninstall", "list", "menu"],
        default="menu",
        help="Action to perform",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target root directory")
    parser.add_argument(
        "--global", dest="is_global", action="store_true", help="Force global scope"
    )
    parser.add_argument("--local", dest="is_local", action="store_true", help="Force local scope")
    parser.add_argument("--all", dest="all_rules", action="store_true", help="Select all rules")
    parser.add_argument(
        "--tech",
        dest="tech",
        type=str,
        default=None,
        help="Filter rules by technology stack (e.g. python, java, all)",
    )
    parser.add_argument(
        "--agent",
        dest="agent",
        type=str,
        default="agents",
        choices=["agents", "all"],
        help="Write shared rules to AGENTS.md; provider-specific bridges remain optional",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    catalog = RuleCatalog()

    if args.action == "list":
        list_catalog(catalog)
        return

    if args.action == "uninstall":
        if args.is_global or args.is_local:
            storage = (
                RuleStorage.global_storage()
                if args.is_global
                else RuleStorage.local_storage(args.root)
            )
            storage.delete_owned()

            # Select adapters to uninstall
            if args.agent == "all":
                adapters_to_uninstall = list(ALL_ADAPTERS.values())
            elif args.agent in ALL_ADAPTERS:
                # If explicitly specified (or default), uninstall for all if default, or specific if non-default
                if "--agent" in (argv or sys.argv[1:]):
                    adapters_to_uninstall = [ALL_ADAPTERS[args.agent]]
                else:
                    adapters_to_uninstall = list(ALL_ADAPTERS.values())
            else:
                adapters_to_uninstall = list(ALL_ADAPTERS.values())

            for adapter in adapters_to_uninstall:
                adapter.uninstall(args.root, args.is_global)
            return
        run_uninstaller(args.root)
        return

    if args.action == "install":
        if args.is_global or args.is_local or args.tech:
            storage = (
                RuleStorage.global_storage()
                if args.is_global
                else RuleStorage.local_storage(args.root)
            )
            rules_to_save = catalog.rules
            if args.tech:
                rules_to_save = filter_rules_by_tech(rules_to_save, args.tech)

            saved = storage.save_rules(rules_to_save)

            # Target selected adapters
            if args.agent == "all":
                selected_adapters = list(ALL_ADAPTERS.values())
            elif args.agent in ALL_ADAPTERS:
                selected_adapters = [ALL_ADAPTERS[args.agent]]
            else:
                selected_adapters = [ALL_ADAPTERS["agents"]]

            for adapter in selected_adapters:
                adapter.install(rules_to_save, saved, args.root, args.is_global, tech=args.tech)
            return
        run_interactive_installer(catalog, args.root)
        return

    # Default interactive menu
    show_banner()
    action_idx = select_one(
        "What would you like to do?",
        [
            "📥 Install / Update Rules",
            "🗑️  Uninstall Rules",
            "📚 List Rule Catalog",
        ],
        default_index=0,
    )

    if action_idx == 0:
        run_interactive_installer(catalog, args.root)
    elif action_idx == 1:
        run_uninstaller(args.root)
    else:
        list_catalog(catalog)


if __name__ == "__main__":
    main()
