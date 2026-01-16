#!/usr/bin/env python3
"""
Ninox CLI - Typer-basierte Kommandozeile
=========================================
Moderne CLI für den Ninox API Schema & Script Extractor.

Verwendung:
    python ninox_cli.py extract --domain https://ninox.example.com --team TEAM_ID --apikey API_KEY
    python ninox_cli.py search "Suchbegriff"
    python ninox_cli.py deps "Tabellenname"
    python ninox_cli.py stats
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import print as rprint

# Importiere Klassen aus dem bestehenden Modul
from ninox_api_extractor import (
    NinoxAPIClient,
    NinoxSchemaExtractor,
    get_code_preview,
    SYNTAX_HIGHLIGHTING_AVAILABLE,
)

# Typer App erstellen
app = typer.Typer(
    name="ninox",
    help="Ninox API Schema & Script Extractor - Extrahiert und analysiert Ninox-Datenbankstrukturen",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

# Standard-Datenbankpfad
DEFAULT_DB = "ninox_schema.db"


def load_config(config_path: str, env: str) -> dict:
    """Lädt Konfiguration aus YAML-Datei"""
    import yaml
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('environments', {}).get(env, {})


def get_extractor(db_path: str) -> NinoxSchemaExtractor:
    """Erstellt einen Extractor mit bestehender DB"""
    extractor = NinoxSchemaExtractor(None, db_path)
    extractor.conn = sqlite3.connect(db_path)
    extractor.conn.row_factory = sqlite3.Row
    return extractor


# =============================================================================
# EXTRACT Command
# =============================================================================

@app.command()
def extract(
    domain: Optional[str] = typer.Option(
        None, "--domain", "-d",
        help="Ninox Domain (z.B. https://app.ninox.com)",
        envvar="NINOX_DOMAIN"
    ),
    team: Optional[str] = typer.Option(
        None, "--team", "-t",
        help="Team/Workspace ID",
        envvar="NINOX_TEAM_ID"
    ),
    apikey: Optional[str] = typer.Option(
        None, "--apikey", "-k",
        help="API Key",
        envvar="NINOX_API_KEY"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", "-c",
        help="Config YAML Datei",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    env: str = typer.Option(
        "dev", "--env", "-e",
        help="Environment in Config-Datei"
    ),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Ausgabedatei"
    ),
    databases: Optional[List[str]] = typer.Option(
        None, "--databases",
        help="Nur bestimmte Datenbank-IDs extrahieren"
    ),
):
    """
    Extrahiert Schema und Scripts von der Ninox API.

    Credentials können via CLI-Argumente, Config-Datei oder Umgebungsvariablen
    bereitgestellt werden.
    """
    # .env laden falls vorhanden
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Credentials zusammenstellen
    team_name = None

    if config:
        cfg = load_config(str(config), env)
        domain = domain or cfg.get('domain')
        team = team or cfg.get('workspaceId') or cfg.get('teamId')
        team_name = cfg.get('teamName') or cfg.get('name') or env
        apikey = apikey or cfg.get('apiKey')

    # Fallback auf Umgebungsvariablen
    domain = domain or os.getenv('NINOX_DOMAIN')
    team = team or os.getenv('NINOX_TEAM_ID')
    team_name = team_name or os.getenv('NINOX_TEAM_NAME') or team
    apikey = apikey or os.getenv('NINOX_API_KEY')

    # Validierung
    if not all([domain, team, apikey]):
        console.print("[red]Fehler:[/red] domain, team und apikey müssen angegeben werden!")
        console.print("\nOptionen:")
        console.print("  1. CLI-Argumente: --domain, --team, --apikey")
        console.print("  2. Config-Datei: --config config.yaml --env dev")
        console.print("  3. Umgebungsvariablen: NINOX_DOMAIN, NINOX_TEAM_ID, NINOX_API_KEY")
        raise typer.Exit(1)

    console.print(f"[blue]Verbinde mit:[/blue] {domain}")

    # Client erstellen
    client = NinoxAPIClient(domain, team, apikey, team_name=team_name)

    # Team-Namen von API holen wenn nicht in Config
    if not team_name or team_name == team:
        api_team_name = client.get_team_name()
        client.team_name = api_team_name
        console.print(f"[blue]Team:[/blue] {api_team_name} ({team})")
    else:
        console.print(f"[blue]Team:[/blue] {team_name} ({team})")

    # Extraktion durchführen
    extractor = NinoxSchemaExtractor(client, str(db))

    with console.status("[bold green]Extrahiere Daten..."):
        stats = extractor.extract_all(databases)

    # Ergebnis anzeigen
    console.print("\n[green]Extraktion abgeschlossen:[/green]")

    table = Table(show_header=False, box=None)
    table.add_column("Metrik", style="cyan")
    table.add_column("Anzahl", style="white", justify="right")

    for key, value in stats.items():
        table.add_row(key.capitalize(), str(value))

    console.print(table)
    console.print(f"\n[green]Gespeichert in:[/green] {db}")

    extractor.close()


# =============================================================================
# SEARCH Command
# =============================================================================

@app.command()
def search(
    query: str = typer.Argument(..., help="Suchbegriff"),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
    table: Optional[str] = typer.Option(
        None, "--table", "-t",
        help="Filter auf Tabelle"
    ),
    code_type: Optional[str] = typer.Option(
        None, "--type",
        help="Filter auf Code-Typ (z.B. onClick, fn, afterUpdate)"
    ),
    limit: int = typer.Option(
        20, "--limit", "-n",
        help="Maximale Anzahl Ergebnisse"
    ),
    show_code: bool = typer.Option(
        False, "--show-code", "-c",
        help="Vollständigen Code anzeigen"
    ),
):
    """
    Volltextsuche in Scripts und Formeln.

    Beispiele:
        ninox search "select Kunden"
        ninox search "http(" --type onClick
        ninox search "afterUpdate" --table Aufträge --show-code
    """
    extractor = get_extractor(str(db))

    results = extractor.search_scripts(
        query,
        table_name=table,
        code_type=code_type,
        limit=limit
    )

    console.print(f"\n[cyan]{len(results)}[/cyan] Treffer für '[yellow]{query}[/yellow]':\n")

    for i, r in enumerate(results, 1):
        # Location zusammenbauen
        loc = f"{r['database_name']}.{r['table_name'] or '(DB)'}"
        if r['element_name']:
            loc += f".{r['element_name']}"

        console.print(f"[bold cyan]{i}.[/bold cyan] {loc}")
        console.print(f"   [dim]Typ:[/dim] {r['code_type']} ({r['code_category']}) | [dim]Zeilen:[/dim] {r['line_count']}")

        if show_code:
            # Vollständigen Code mit Syntax-Highlighting anzeigen
            console.print()
            syntax = Syntax(r['code'], "javascript", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title=f"{r['code_type']}", border_style="dim"))
        else:
            # Nur Preview
            if SYNTAX_HIGHLIGHTING_AVAILABLE:
                code_preview = get_code_preview(r['code'], max_length=150)
            else:
                code_preview = r['code'][:150].replace('\n', ' ')
            console.print(f"   [dim]{code_preview}...[/dim]")

        console.print()

    extractor.close()


# =============================================================================
# DEPS Command
# =============================================================================

@app.command()
def deps(
    table_name: str = typer.Argument(..., help="Tabellenname"),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
):
    """
    Zeigt Abhängigkeiten einer Tabelle.

    Listet alle Verknüpfungen und Formel-Referenzen für eine Tabelle auf.
    """
    extractor = get_extractor(str(db))

    deps_data = extractor.get_table_dependencies(table_name)

    console.print(f"\n[bold]Abhängigkeiten für '[cyan]{table_name}[/cyan]':[/bold]\n")

    # Referenziert (N:1)
    console.print("[bold green]→ Referenziert (N:1):[/bold green]")
    if deps_data['references']:
        ref_table = Table(show_header=True, box=None)
        ref_table.add_column("Feld", style="cyan")
        ref_table.add_column("→", style="dim")
        ref_table.add_column("Ziel-Tabelle", style="yellow")
        ref_table.add_column("Info", style="dim")

        for ref in deps_data['references']:
            comp = "Composition" if ref['is_composition'] else ""
            ref_table.add_row(
                ref['source_field_name'],
                "→",
                ref['target_table_name'],
                comp
            )
        console.print(ref_table)
    else:
        console.print("   [dim](keine)[/dim]")

    console.print()

    # Wird referenziert von (1:N)
    console.print("[bold blue]← Wird referenziert von (1:N):[/bold blue]")
    if deps_data['referenced_by']:
        back_table = Table(show_header=True, box=None)
        back_table.add_column("Tabelle", style="cyan")
        back_table.add_column("Feld", style="yellow")

        for ref in deps_data['referenced_by']:
            back_table.add_row(
                ref['source_table_name'],
                ref['source_field_name']
            )
        console.print(back_table)
    else:
        console.print("   [dim](keine)[/dim]")

    console.print()

    # Formel-Referenzen
    formula_count = len(deps_data['formula_references'])
    console.print(f"[bold magenta]Formel-Referenzen:[/bold magenta] {formula_count}")

    if deps_data['formula_references']:
        for ref in deps_data['formula_references'][:5]:
            console.print(f"   {ref['source_table_name']}.{ref['source_field_name']} [dim]({ref['found_in_code_type']})[/dim]")
        if formula_count > 5:
            console.print(f"   [dim]... und {formula_count - 5} weitere[/dim]")

    extractor.close()


# =============================================================================
# STATS Command
# =============================================================================

@app.command()
def stats(
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
):
    """
    Zeigt Statistiken über die extrahierten Daten.
    """
    extractor = get_extractor(str(db))

    stats_data = extractor.get_statistics()

    console.print("\n[bold]Ninox Schema Statistiken[/bold]\n")

    # Hauptzahlen
    main_table = Table(show_header=False, box=None)
    main_table.add_column("Metrik", style="cyan", width=20)
    main_table.add_column("Anzahl", style="white", justify="right")

    main_table.add_row("Datenbanken", str(stats_data['databases_count']))
    main_table.add_row("Tabellen", str(stats_data['tables_count']))
    main_table.add_row("Felder", str(stats_data['fields_count']))
    main_table.add_row("Verknüpfungen", str(stats_data['relationships_count']))
    main_table.add_row("Scripts", str(stats_data['scripts_count']))

    console.print(Panel(main_table, title="Übersicht", border_style="blue"))

    # Scripts nach Typ
    console.print("\n[bold]Scripts nach Typ:[/bold]")
    type_table = Table(show_header=True, box=None)
    type_table.add_column("Typ", style="cyan")
    type_table.add_column("Anzahl", style="white", justify="right")

    for typ, count in list(stats_data['scripts_by_type'].items())[:10]:
        type_table.add_row(typ, str(count))

    console.print(type_table)

    # Verknüpfungen nach Typ
    console.print("\n[bold]Verknüpfungen nach Typ:[/bold]")
    rel_table = Table(show_header=True, box=None)
    rel_table.add_column("Typ", style="cyan")
    rel_table.add_column("Anzahl", style="white", justify="right")

    for typ, count in stats_data['relationships_by_type'].items():
        rel_table.add_row(typ, str(count))

    console.print(rel_table)

    # Top Tabellen
    console.print("\n[bold]Top Tabellen (nach Scripts):[/bold]")
    top_table = Table(show_header=True, box=None)
    top_table.add_column("Tabelle", style="cyan")
    top_table.add_column("Scripts", style="white", justify="right")

    for table_name, count in list(stats_data['top_tables_by_scripts'].items())[:5]:
        top_table.add_row(table_name, str(count))

    console.print(top_table)

    extractor.close()


# =============================================================================
# LIST Command
# =============================================================================

@app.command("list")
def list_cmd(
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
    database: Optional[str] = typer.Option(
        None, "--database", "-d",
        help="Zeigt Tabellen dieser Datenbank"
    ),
):
    """
    Listet Datenbanken oder Tabellen auf.

    Ohne --database werden alle Datenbanken aufgelistet.
    Mit --database werden die Tabellen dieser Datenbank angezeigt.
    """
    extractor = get_extractor(str(db))

    if database:
        tables = extractor.list_tables(database)
        console.print(f"\n[bold]Tabellen in [cyan]{database}[/cyan]:[/bold]\n")

        table = Table(show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Felder", justify="right")

        for t in tables:
            table.add_row(t['name'], str(t['field_count']))

        console.print(table)
    else:
        dbs = extractor.list_databases()
        console.print(f"\n[bold]Datenbanken ({len(dbs)}):[/bold]\n")

        table = Table(show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("ID", style="dim")
        table.add_column("Tabellen", justify="right")
        table.add_column("Scripts", justify="right")

        for d in dbs:
            table.add_row(
                d['name'],
                d['id'],
                str(d['table_count']),
                str(d['code_count'])
            )

        console.print(table)

    extractor.close()


# =============================================================================
# EXPORT Command
# =============================================================================

@app.command()
def export(
    output: Path = typer.Argument(..., help="Ausgabedatei (JSON)"),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
):
    """
    Exportiert alle Daten als JSON.
    """
    extractor = get_extractor(str(db))

    with console.status("[bold green]Exportiere..."):
        extractor.export_to_json(str(output))

    console.print(f"[green]Exportiert:[/green] {output}")
    extractor.close()


# =============================================================================
# HTML Command
# =============================================================================

@app.command()
def html(
    output: Path = typer.Argument(..., help="HTML Ausgabedatei"),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
    database: Optional[str] = typer.Option(
        None, "--database", "-d",
        help="Nur diese Datenbank exportieren"
    ),
):
    """
    Exportiert Scripts als HTML mit Syntax-Highlighting.
    """
    extractor = get_extractor(str(db))

    with console.status("[bold green]Generiere HTML..."):
        extractor.export_scripts_to_html(str(output), database)

    console.print(f"[green]HTML exportiert:[/green] {output}")
    extractor.close()


# =============================================================================
# MARKDOWN Command
# =============================================================================

@app.command()
def md(
    output: Path = typer.Argument(..., help="Markdown Ausgabedatei (.md)"),
    db: Path = typer.Option(
        DEFAULT_DB, "--db",
        help="SQLite Datenbank",
        exists=True,
    ),
    database: Optional[str] = typer.Option(
        None, "--database", "-d",
        help="Nur diese Datenbank exportieren"
    ),
):
    """
    Generiert Markdown-Dokumentation.

    Erstellt eine vollständige Dokumentation mit Tabellenstruktur,
    Feldern und allen Scripts.
    """
    extractor = get_extractor(str(db))

    with console.status("[bold green]Generiere Markdown..."):
        extractor.export_to_markdown(str(output), database)

    console.print(f"[green]Markdown exportiert:[/green] {output}")
    extractor.close()


# =============================================================================
# VERSION Command
# =============================================================================

@app.command()
def version():
    """Zeigt die Version an."""
    console.print("[bold]Ninox CLI[/bold] v1.0.0")
    console.print("[dim]Typer-basierte Kommandozeile für den Ninox API Extractor[/dim]")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    app()
