# -*- coding: utf-8 -*-
"""
@Time    : 2025/6/11 09:04
@Author  : QIN2DIM
@GitHub  : https://github.com/QIN2DIM
@Desc    :
"""

import typer
from typer import Option
from rich.console import Console

from tnt.tools import scan_services
from tnt.tools import to_excel
from tnt.tools import visualize

app = typer.Typer(
    name="tnt",
    help="A toolkit for scanning and visualizing docker-compose services.",
    add_completion=False,
)

console = Console()


@app.command()
def main(
    scan: bool = Option(True, "--scan/--no-scan", help="Scan running docker-compose services."),
    excel: bool = Option(True, "--excel/--no-excel", help="Convert scan results to an Excel file."),
    viz: bool = Option(
        True, "--visualize/--no-visualize", help="Visualize service dependencies from scan results."
    ),
):
    """
    TNT command-line interface.
    """
    if not any([scan, excel, viz]):
        console.print("[yellow]No action selected. Use --help for more information.[/yellow]")
        return

    if scan:
        console.print("[bold green]>>> Running Service Scan...[/bold green]")
        try:
            scan_services()
            console.print("[bold green]<<< Service Scan completed.[/bold green]\n")
        except Exception as e:
            console.print(f"[bold red]An error occurred during service scan: {e}[/bold red]")
            # If scan fails, it doesn't make sense to run the other tools
            return

    if excel:
        console.print("[bold green]>>> Generating Excel report...[/bold green]")
        try:
            to_excel()
            console.print("[bold green]<<< Excel report generated.[/bold green]\n")
        except Exception as e:
            console.print(f"[bold red]An error occurred during Excel generation: {e}[/bold red]")

    if viz:
        console.print("[bold green]>>> Generating Service Visualization...[/bold green]")
        try:
            visualize()
            console.print("[bold green]<<< Service Visualization generated.[/bold green]\n")
        except Exception as e:
            console.print(
                f"[bold red]An error occurred during service visualization: {e}[/bold red]"
            )


if __name__ == "__main__":
    app()
