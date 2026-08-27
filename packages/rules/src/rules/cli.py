from __future__ import annotations

import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

from .core.catalog import RuleCatalog, RuleDefinition
from .core.storage import RuleStorage
from .adapters import ALL_ADAPTERS

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

    console.print("\n[bold yellow]? Select target installation scope:[/bold yellow]")
    console.print("  [1] 🌐 [bold]Global[/bold] (Machine-wide in ~/.specops/rules/ for all projects)")
    console.print("  [2] 📁 [bold]Local[/bold] (Project-local in .specops/rules/)")
    scope_choice = Prompt.ask("Enter choice", choices=["1", "2"], default="1")
    is_global = (scope_choice == "1")

    storage = RuleStorage.global_storage() if is_global else RuleStorage.local_storage(root)

    console.print("\n[bold yellow]? Select AI agents to configure:[/bold yellow]")
    console.print("  [0] ✨ [bold green]All Detected Agents[/bold green] (Claude, Cursor, Codex, Windsurf, Gemini)")
    for idx, (aid, adapter) in enumerate(ALL_ADAPTERS.items(), start=1):
        console.print(f"  [{idx}] {adapter.display_name}")

    agent_choice = Prompt.ask("Enter agent numbers separated by commas, or 0 for All", default="0")
    if agent_choice.strip() == "0":
        selected_adapters = list(ALL_ADAPTERS.values())
    else:
        indices = [int(x.strip()) for x in agent_choice.split(",") if x.strip().isdigit()]
        selected_adapters = [list(ALL_ADAPTERS.values())[i - 1] for i in indices if 1 <= i <= len(ALL_ADAPTERS)]
        if not selected_adapters:
            selected_adapters = list(ALL_ADAPTERS.values())

    console.print("\n[bold yellow]? Select Rules & Stacks to install:[/bold yellow]")
    console.print("  [A] ✨ [bold green]Select ALL 28 Rules[/bold green] (Full Enterprise Suite)")
    console.print("  [1] 🏛️  All Core Rules (Clean Code, SOLID, DDD, Architecture, Testing, Security)")
    console.print("  [2] 💻 All Language Stacks (Java, C#, TS, React, Python, Go, Rust, Kotlin, PHP, Dart)")
    console.print("  [3] ☁️  All Infrastructure & DB Rules (Migrations, SQL, Docker, K8s, CI/CD, APIs)")
    console.print("  [4] 📐 All Documentation & Diagrams Rules (C4 Model, Mermaid, ADRs)")

    rule_choice = Prompt.ask("Enter choice (A/1/2/3/4 or comma-separated)", default="A").upper()

    chosen_rules: list[RuleDefinition] = []
    by_cat = catalog.by_category()

    if "A" in rule_choice:
        chosen_rules = catalog.rules
    else:
        if "1" in rule_choice:
            chosen_rules.extend(by_cat.get("1-core", []))
        if "2" in rule_choice:
            chosen_rules.extend(by_cat.get("2-stacks", []))
        if "3" in rule_choice:
            chosen_rules.extend(by_cat.get("3-infrastructure", []))
        if "4" in rule_choice:
            chosen_rules.extend(by_cat.get("4-docs", []))

    if not chosen_rules:
        chosen_rules = catalog.rules

    saved_path = storage.save_rules(chosen_rules)
    console.print(f"\n[bold green]✔[/bold green] Saved [bold]{len(chosen_rules)} rules[/bold] to [cyan]{saved_path}[/cyan]")

    for adapter in selected_adapters:
        target = adapter.install(chosen_rules, saved_path, root, is_global)
        console.print(f"[bold green]✔[/bold green] Configured {adapter.display_name}: [cyan]{target}[/cyan]")

    console.print("\n[bold green]🎉 Rules installation completed successfully![/bold green]")


def run_uninstaller(root: Path) -> None:
    show_banner()
    console.print("\n[bold yellow]? Select scope to uninstall:[/bold yellow]")
    console.print("  [1] 🌐 [bold]Global[/bold] (~/)")
    console.print("  [2] 📁 [bold]Local[/bold] (Current Project)")
    scope_choice = Prompt.ask("Enter choice", choices=["1", "2"], default="1")
    is_global = (scope_choice == "1")

    storage = RuleStorage.global_storage() if is_global else RuleStorage.local_storage(root)
    storage.delete_all()

    for adapter in ALL_ADAPTERS.values():
        res = adapter.uninstall(root, is_global)
        if res:
            console.print(f"[bold green]✔[/bold green] Cleaned {adapter.display_name}: [cyan]{res}[/cyan]")

    console.print("\n[bold green]✨ All rules successfully uninstalled and user files preserved.[/bold green]")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rules", description="SpecOps Rules — Software Engineering Standards TUI")
    parser.add_argument("action", nargs="?", choices=["install", "uninstall", "list", "menu"], default="menu", help="Action to perform")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target root directory")
    parser.add_argument("--global", dest="is_global", action="store_true", help="Force global scope")
    parser.add_argument("--local", dest="is_local", action="store_true", help="Force local scope")
    parser.add_argument("--all", dest="all_rules", action="store_true", help="Select all rules")
    args = parser.parse_args(argv or sys.argv[1:])

    catalog = RuleCatalog()

    if args.action == "list":
        list_catalog(catalog)
        return

    if args.action == "uninstall":
        if args.is_global or args.is_local:
            storage = RuleStorage.global_storage() if args.is_global else RuleStorage.local_storage(args.root)
            storage.delete_all()
            for adapter in ALL_ADAPTERS.values():
                adapter.uninstall(args.root, args.is_global)
            return
        run_uninstaller(args.root)
        return

    if args.action == "install":
        if args.is_global or args.is_local:
            storage = RuleStorage.global_storage() if args.is_global else RuleStorage.local_storage(args.root)
            rules_to_save = catalog.rules if args.all_rules else catalog.rules
            saved = storage.save_rules(rules_to_save)
            for adapter in ALL_ADAPTERS.values():
                adapter.install(rules_to_save, saved, args.root, args.is_global)
            return
        run_interactive_installer(catalog, args.root)
        return

    show_banner()
    console.print("\n[bold yellow]? What would you like to do?[/bold yellow]")
    console.print("  [1] 📥 [bold]Install / Update Rules[/bold]")
    console.print("  [2] 🗑️  [bold]Uninstall Rules[/bold]")
    console.print("  [3] 📚 [bold]List Rule Catalog[/bold]")
    action_choice = Prompt.ask("Enter choice", choices=["1", "2", "3"], default="1")

    if action_choice == "1":
        run_interactive_installer(catalog, args.root)
    elif action_choice == "2":
        run_uninstaller(args.root)
    else:
        list_catalog(catalog)


if __name__ == "__main__":
    main()
