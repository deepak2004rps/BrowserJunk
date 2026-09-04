#!/usr/bin/env python3
"""
main.py – CLI entry point for the BrowserVault Demo Data Populator.

Usage examples:
  python main.py                           # auto-detect browsers, populate all
  python main.py --browsers chrome firefox # target specific browsers
  python main.py --categories history passwords bookmarks
  python main.py --personas 3 --seed 42   # reproducible, 3 personas
  python main.py --dry-run                 # log actions without writing
  python main.py --list-browsers           # show detected browsers

Run `python main.py --help` for full options.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure core/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from core.browsers import (
    BROWSER_REGISTRY,
    DataCategory,
    build_populators,
    detect_installed_browsers,
)
from core.persona import generate_personas
from core.helpers import OUTPUT_DIR, get_logger, save_reports

_CHROMIUM_EXE = {"chrome": "chrome.exe", "edge": "msedge.exe", "brave": "brave.exe"}


def _write_launchers(pop) -> list[Path]:
    """Write one .bat per generated profile that opens that exact profile
    directly, bypassing the fact that a normal double-click always reopens
    the last active profile instead of a newly created one."""
    written: list[Path] = []
    for persona in pop.personas:
        profile_name = pop.profile_name_for(persona)
        if pop.key == "firefox":
            exe, args = "firefox.exe", f'-P "{profile_name}"'
        else:
            exe = _CHROMIUM_EXE.get(pop.key)
            if not exe:
                continue
            args = f'--profile-directory="{profile_name}"'

        path = OUTPUT_DIR / f"open_{pop.key}_{profile_name}.bat"
        path.write_text(
            f'@echo off\r\nstart "" "{exe}" {args}\r\n',
            encoding="utf-8",
        )
        written.append(path)
    return written

console = Console()
logger = get_logger("cli")

_CONFIG_PATH = Path(__file__).parent / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[yellow]Warning:[/yellow] could not read {_CONFIG_PATH.name} ({exc}), using built-in defaults.")
        return {}


_CONFIG = _load_config()
_CFG_BROWSERS = _CONFIG.get("browsers", "auto")
_CFG_CATEGORIES = _CONFIG.get("categories", "all")

_BANNER = """
[bold cyan] ██████╗ ██████╗  ██████╗ ██╗    ██╗███████╗███████╗██████╗ [/bold cyan]
[bold cyan]██╔══██╗██╔══██╗██╔═══██╗██║    ██║██╔════╝██╔════╝██╔══██╗[/bold cyan]
[bold cyan]██████╔╝██████╔╝██║   ██║██║ █╗ ██║███████╗█████╗  ██████╔╝[/bold cyan]
[bold cyan]██╔══██╗██╔══██╗██║   ██║██║███╗██║╚════██║██╔══╝  ██╔══██╗[/bold cyan]
[bold cyan]██████╔╝██║  ██║╚██████╔╝╚███╔███╔╝███████║███████╗██║  ██║[/bold cyan]
[bold cyan]╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═╝[/bold cyan]
[dim]        Demo Data Populator  ·  Browser Vault Utility[/dim]
"""

ALL_CATEGORIES = sorted(DataCategory.ALL)
ALL_BROWSERS = list(BROWSER_REGISTRY.keys())


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--browsers", "-b",
    multiple=True,
    type=click.Choice(ALL_BROWSERS, case_sensitive=False),
    help="Browsers to populate. Repeatable. Default: auto-detect installed.",
)
@click.option(
    "--categories", "-c",
    multiple=True,
    type=click.Choice(ALL_CATEGORIES, case_sensitive=False),
    help="Data categories to populate. Repeatable. Default: all.",
)
@click.option(
    "--personas", "-n",
    default=_CONFIG.get("personas", 2),
    show_default=True,
    type=click.IntRange(1, 10),
    help="Profiles (unique personas) to create per browser. Personas are never "
         "shared between browsers.",
)
@click.option(
    "--seed", "-s",
    default=_CONFIG.get("seed", None),
    type=int,
    help="Random seed for reproducible data. Omit for random each run.",
)
@click.option(
    "--profile-name",
    default=_CONFIG.get("profile_name", "BVaultDemo"),
    show_default=True,
    help="Name of the demo profile folder to create inside each browser.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=_CONFIG.get("dry_run", False),
    help="Log actions without writing any files.",
)
@click.option(
    "--force-create",
    is_flag=True,
    default=False,
    help="Create browser User Data dirs even if the browser isn't installed.",
)
@click.option(
    "--list-browsers",
    is_flag=True,
    default=False,
    help="List detected installed browsers and exit.",
)
@click.option(
    "--no-report",
    is_flag=True,
    default=False,
    help="Skip generating HTML/JSON run reports.",
)
def main(
    browsers,
    categories,
    personas,
    seed,
    profile_name,
    dry_run,
    force_create,
    list_browsers,
    no_report,
):
    """
    BrowserVault Demo Data Populator.

    Automatically populates browser profiles with synthetic, non-sensitive
    test data for demonstration and validation purposes.
    """
    console.print(_BANNER)

    # ── --list-browsers mode ──────────────────────────────────────────────
    if list_browsers:
        detected = detect_installed_browsers()
        t = Table(title="Browser Detection", box=box.ROUNDED, style="cyan")
        t.add_column("Key", style="bold")
        t.add_column("Name")
        t.add_column("Status")
        for key, meta in BROWSER_REGISTRY.items():
            status = "[green]● Installed[/green]" if key in detected else "[dim]○ Not found[/dim]"
            t.add_row(key, meta["name"], status)
        console.print(t)
        return

    # ── Every run gets its own profile, never overwrites a previous one ────
    profile_name = f"{profile_name}_{time.strftime('%Y%m%d_%H%M%S')}"

    # ── Resolve inputs (CLI flags win, else fall back to config.json) ──────
    if browsers:
        browser_list = list(browsers)
    elif isinstance(_CFG_BROWSERS, list) and _CFG_BROWSERS:
        browser_list = _CFG_BROWSERS
    else:
        browser_list = None  # "auto" -> detect installed

    if categories:
        category_set = set(categories)
    elif isinstance(_CFG_CATEGORIES, list) and _CFG_CATEGORIES:
        category_set = set(_CFG_CATEGORIES)
    else:
        category_set = None  # "all" -> every category

    if dry_run:
        console.print(Panel("[yellow]DRY RUN MODE – no files will be written.[/yellow]", style="yellow"))

    # ── Build populators first, so we know how many browsers we target ────
    console.print("\n[cyan]Building browser populators…[/cyan]")
    try:
        pop_list = build_populators(
            browser_keys=browser_list,
            personas=[],  # assigned below
            categories=category_set,
            dry_run=dry_run,
            demo_profile=profile_name,
            force_create=force_create,
        )
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    if not pop_list:
        console.print(
            "[yellow]No supported browsers detected. "
            "Use --force-create to create profiles anyway, "
            "or --list-browsers to check detection.[/yellow]"
        )
        sys.exit(0)

    # ── Generate a disjoint set of personas per browser ──────────────────
    total_personas = personas * len(pop_list)
    console.print(
        f"\n[cyan]Generating {total_personas} persona(s) "
        f"— {personas} per browser, none shared…[/cyan]"
    )
    persona_list = generate_personas(count=total_personas, base_seed=seed)

    for i, pop in enumerate(pop_list):
        pop.personas = persona_list[i * personas:(i + 1) * personas]
        console.print(f"  [bold]{pop.name}[/bold]:")
        for p in pop.personas:
            console.print(
                f"    [green]✓[/green] {p.full_name} "
                f"<{p.email}> · {len(p.passwords)} passwords · {len(p.cards)} card(s)"
            )

    console.print(f"\n  Targeting [bold]{len(pop_list)}[/bold] browser(s): "
                  f"{', '.join(p.name for p in pop_list)}")

    # ── Run population ────────────────────────────────────────────────────
    all_results: dict = {}
    browsers_run: list[str] = []
    launchers: list[Path] = []
    start = time.time()

    for pop in pop_list:
        console.rule(f"[bold magenta]{pop.name}[/bold magenta]")
        result = pop.run()
        all_results.update(result)
        browsers_run.append(pop.name)
        if not dry_run:
            launchers.extend(_write_launchers(pop))

    elapsed = time.time() - start
    console.rule("[bold green]Complete[/bold green]")
    console.print(f"\n[green]✓[/green] All done in [bold]{elapsed:.1f}s[/bold].")

    if launchers:
        console.print(
            "\n[cyan]A normal double-click reopens your regular profile — "
            "use these to open the demo profile directly:[/cyan]"
        )
        for path in launchers:
            console.print(f"  [cyan]{path}[/cyan]")

    # ── Reports ───────────────────────────────────────────────────────────
    if not no_report and all_results:
        json_path, html_path = save_reports(all_results, persona_list, browsers_run)
        console.print(f"\n[dim]Reports saved:[/dim]")
        console.print(f"  JSON → [cyan]{json_path}[/cyan]")
        console.print(f"  HTML → [cyan]{html_path}[/cyan]")


if __name__ == "__main__":
    main()
