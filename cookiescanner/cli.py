"""Command-line entrypoint.

Usage:
    cookie-scanner scan cookies.json
    cookie-scanner scan cookies.json --only perplexity.ai
    cookie-scanner scan cookies.json --proxy http://user:pass@host:port
    cookie-scanner scan cookies.json --json    # machine-readable

Per-site cookie files (recommended when domains differ):
    cookie-scanner scan -c perplexity.json -c blackbox.json -c manus.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .cookies import CookieJar, load_cookies, merge_jars
from .scanner import scan_all


app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


def _load_jar(positional: list[Path], extra: list[Path]) -> CookieJar:
    jars: list[CookieJar] = []
    for path in list(positional) + list(extra):
        try:
            jars.append(load_cookies(path))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]error loading {path}: {e}[/red]")
            sys.exit(2)
    return merge_jars(jars)


@app.command()
def scan(
    cookies: list[Path] = typer.Argument(None, exists=True, help="Cookie file(s). Multiple allowed."),
    cookie: list[Path] = typer.Option([], "--cookie", "-c", exists=True, help="Additional cookie file."),
    only: list[str] = typer.Option([], "--only", help="Only scan named sites (e.g. perplexity.ai)."),
    proxy: str = typer.Option(None, "--proxy", help="HTTP(S) proxy URL (e.g. http://user:pass@host:port)."),
    output_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON only."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show every endpoint that was probed."),
):
    """Scan one or more cookie sources and report alive/dead + account info."""
    sources = list(cookies or []) + list(cookie or [])
    if not sources:
        console.print("[red]No cookie file provided.[/red]")
        raise typer.Exit(2)

    jar = _load_jar(cookies or [], cookie or [])

    if not output_json:
        console.print(f"Loaded [bold]{len(jar)}[/bold] cookies from {len(sources)} file(s).")
        console.print()

    results = scan_all(jar, proxy=proxy, only=only or None)

    if output_json:
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
        return

    for r in results:
        status = "[green]ALIVE[/green]" if r.alive else "[red]DEAD[/red]"
        console.rule(f"{r.site}  —  {status}")
        if r.error:
            console.print(f"[yellow]note:[/yellow] {r.error}")
        if r.info:
            table = Table(show_header=False, box=None, pad_edge=False)
            table.add_column("key", style="dim")
            table.add_column("value")
            for k in sorted(r.info.keys()):
                v = r.info[k]
                table.add_row(k, str(v))
            console.print(table)
        elif r.alive:
            console.print("[dim]no extra account info extracted[/dim]")

        if verbose:
            console.print()
            console.print("[dim]endpoints probed:[/dim]")
            for entry in r.endpoints_tried:
                console.print(f"  [dim]{entry.get('status'):>4}[/dim]  {entry.get('url')}")
        console.print()


if __name__ == "__main__":  # pragma: no cover
    app()
