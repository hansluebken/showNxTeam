#!/usr/bin/env python3
"""
Ninox Interactive CLI
=====================
Interaktive Kommandozeile für den Ninox API Schema & Script Extractor.
Kombiniert Typer, Rich und questionary für eine moderne Benutzererfahrung.

Verwendung:
    python ninox_interactive.py              # Startet interaktiven Modus
    python ninox_interactive.py extract      # Extraktion mit interaktiver Konfiguration
    python ninox_interactive.py search       # Interaktive Suche
    python ninox_interactive.py browse       # Interaktiver Browser
"""

import os
import sys
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

import typer
import questionary
from questionary import Style
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree
from rich.markdown import Markdown
from rich import print as rprint

# Importiere Klassen aus dem bestehenden Modul
from ninox_api_extractor import (
    NinoxAPIClient,
    NinoxSchemaExtractor,
    get_code_preview,
    highlight_code,
    SYNTAX_HIGHLIGHTING_AVAILABLE,
)

# Typer App
app = typer.Typer(
    name="ninox",
    help="Ninox Interactive CLI - Interaktive Schema & Script Analyse",
    add_completion=False,
    rich_markup_mode="rich",
    invoke_without_command=True,
)

console = Console()

# Custom Style für questionary
custom_style = Style([
    ('qmark', 'fg:cyan bold'),
    ('question', 'bold'),
    ('answer', 'fg:cyan'),
    ('pointer', 'fg:cyan bold'),
    ('highlighted', 'fg:cyan bold'),
    ('selected', 'fg:green'),
    ('separator', 'fg:gray'),
    ('instruction', 'fg:gray'),
    ('text', ''),
    ('disabled', 'fg:gray italic'),
])

DEFAULT_DB = "ninox_schema.db"


# =============================================================================
# Hilfsfunktionen
# =============================================================================

def get_extractor(db_path: str) -> NinoxSchemaExtractor:
    """Erstellt einen Extractor mit bestehender DB"""
    extractor = NinoxSchemaExtractor(None, db_path)
    extractor.conn = sqlite3.connect(db_path)
    extractor.conn.row_factory = sqlite3.Row
    return extractor


def db_exists(db_path: str) -> bool:
    """Prüft ob die Datenbank existiert"""
    return Path(db_path).exists()


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """Lädt YAML-Konfiguration"""
    import yaml
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def prompt_credentials() -> Dict[str, str]:
    """Fragt Credentials interaktiv ab"""
    console.print("\n[bold cyan]Ninox API Konfiguration[/bold cyan]\n")

    # Prüfe auf bestehende Config-Dateien
    config_files = list(Path('.').glob('*.yaml')) + list(Path('.').glob('*.yml'))
    env_file = Path('.env')

    choices = []
    if config_files:
        choices.append("Config-Datei verwenden")
    if env_file.exists():
        choices.append(".env Datei verwenden")
    choices.append("Manuell eingeben")

    if len(choices) > 1:
        method = questionary.select(
            "Wie möchten Sie die Zugangsdaten bereitstellen?",
            choices=choices,
            style=custom_style
        ).ask()

        if method == "Config-Datei verwenden":
            config_file = questionary.select(
                "Config-Datei auswählen:",
                choices=[str(f) for f in config_files],
                style=custom_style
            ).ask()

            config = load_yaml_config(config_file)
            envs = list(config.get('environments', {}).keys())

            if envs:
                env = questionary.select(
                    "Environment auswählen:",
                    choices=envs,
                    style=custom_style
                ).ask()

                env_config = config['environments'][env]
                return {
                    'domain': env_config.get('domain'),
                    'team_id': env_config.get('workspaceId') or env_config.get('teamId'),
                    'team_name': env_config.get('teamName') or env_config.get('name') or env,
                    'api_key': env_config.get('apiKey'),
                }

        elif method == ".env Datei verwenden":
            from dotenv import load_dotenv
            load_dotenv()
            return {
                'domain': os.getenv('NINOX_DOMAIN'),
                'team_id': os.getenv('NINOX_TEAM_ID'),
                'team_name': os.getenv('NINOX_TEAM_NAME'),
                'api_key': os.getenv('NINOX_API_KEY'),
            }

    # Manuelle Eingabe
    domain = questionary.text(
        "Ninox Domain (z.B. https://app.ninox.com):",
        default=os.getenv('NINOX_DOMAIN', ''),
        style=custom_style
    ).ask()

    team_id = questionary.text(
        "Team/Workspace ID:",
        default=os.getenv('NINOX_TEAM_ID', ''),
        style=custom_style
    ).ask()

    api_key = questionary.password(
        "API Key:",
        style=custom_style
    ).ask()

    return {
        'domain': domain,
        'team_id': team_id,
        'team_name': None,
        'api_key': api_key,
    }


def select_databases(client: NinoxAPIClient) -> List[str]:
    """Lässt Benutzer Datenbanken auswählen"""
    with console.status("[bold green]Lade Datenbanken..."):
        databases = client.get_databases()

    if not databases:
        console.print("[yellow]Keine Datenbanken gefunden.[/yellow]")
        return []

    choices = [
        questionary.Choice(
            title=f"{db['name']} ({db['id']})",
            value=db['id']
        )
        for db in databases
    ]

    # Option für alle
    select_all = questionary.confirm(
        f"Alle {len(databases)} Datenbanken extrahieren?",
        default=True,
        style=custom_style
    ).ask()

    if select_all:
        return None  # None bedeutet alle

    selected = questionary.checkbox(
        "Datenbanken auswählen:",
        choices=choices,
        style=custom_style
    ).ask()

    return selected


# =============================================================================
# MAIN / Interactive Mode
# =============================================================================

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """
    Ninox Interactive CLI - Startet den interaktiven Modus wenn kein Befehl angegeben.
    """
    if ctx.invoked_subcommand is None:
        interactive_main_menu()


def interactive_main_menu():
    """Hauptmenü für interaktiven Modus"""
    console.print(Panel.fit(
        "[bold cyan]Ninox Interactive CLI[/bold cyan]\n"
        "[dim]Schema & Script Extractor für Ninox Datenbanken[/dim]",
        border_style="cyan"
    ))

    while True:
        console.print()

        # Prüfe ob DB existiert
        has_db = db_exists(DEFAULT_DB)

        choices = []
        if has_db:
            choices.extend([
                questionary.Choice("Suchen", value="search"),
                questionary.Choice("Datenbanken durchsuchen", value="browse"),
                questionary.Choice("Abhängigkeiten anzeigen", value="deps"),
                questionary.Choice("Statistiken", value="stats"),
                questionary.Choice("Exportieren", value="export"),
                questionary.Separator(),
            ])

        choices.extend([
            questionary.Choice(
                "Daten extrahieren" + (" (aktualisieren)" if has_db else ""),
                value="extract"
            ),
            questionary.Separator(),
            questionary.Choice("Beenden", value="quit"),
        ])

        action = questionary.select(
            "Was möchten Sie tun?",
            choices=choices,
            style=custom_style
        ).ask()

        if action == "quit" or action is None:
            console.print("[dim]Auf Wiedersehen![/dim]")
            break
        elif action == "extract":
            interactive_extract()
        elif action == "search":
            interactive_search()
        elif action == "browse":
            interactive_browse()
        elif action == "deps":
            interactive_deps()
        elif action == "stats":
            show_stats()
        elif action == "export":
            interactive_export()


# =============================================================================
# EXTRACT Command
# =============================================================================

@app.command()
def extract(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", envvar="NINOX_DOMAIN"),
    team: Optional[str] = typer.Option(None, "--team", "-t", envvar="NINOX_TEAM_ID"),
    apikey: Optional[str] = typer.Option(None, "--apikey", "-k", envvar="NINOX_API_KEY"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    env: str = typer.Option("dev", "--env", "-e"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i/-I",
                                      help="Interaktiver Modus"),
):
    """
    Extrahiert Schema und Scripts von der Ninox API.
    """
    if interactive and not all([domain, team, apikey]) and not config:
        interactive_extract(str(db))
    else:
        # Non-interactive mode
        run_extraction(domain, team, apikey, config, env, str(db), None)


def interactive_extract(db_path: str = DEFAULT_DB):
    """Interaktive Extraktion"""
    console.print("\n[bold]Daten von Ninox API extrahieren[/bold]\n")

    # Credentials abfragen
    creds = prompt_credentials()

    if not all([creds.get('domain'), creds.get('team_id'), creds.get('api_key')]):
        console.print("[red]Fehler: Unvollständige Zugangsdaten[/red]")
        return

    # Client erstellen
    client = NinoxAPIClient(
        creds['domain'],
        creds['team_id'],
        creds['api_key'],
        team_name=creds.get('team_name')
    )

    # Team-Namen holen
    if not creds.get('team_name'):
        with console.status("[bold green]Verbinde..."):
            team_name = client.get_team_name()
            client.team_name = team_name

    console.print(f"\n[green]Verbunden mit:[/green] {client.team_name}")

    # Datenbanken auswählen
    selected_dbs = select_databases(client)

    # Ausgabedatei
    output_db = questionary.text(
        "Ausgabe-Datenbank:",
        default=db_path,
        style=custom_style
    ).ask()

    # Bestätigung
    if not questionary.confirm("Extraktion starten?", default=True, style=custom_style).ask():
        return

    # Extraktion durchführen
    extractor = NinoxSchemaExtractor(client, output_db)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Extrahiere Daten...", total=None)
        stats = extractor.extract_all(selected_dbs)
        progress.update(task, completed=True)

    # Ergebnis anzeigen
    console.print("\n[green]Extraktion abgeschlossen![/green]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Metrik", style="cyan")
    table.add_column("Anzahl", justify="right")

    for key, value in stats.items():
        table.add_row(key.capitalize(), str(value))

    console.print(table)
    console.print(f"\n[dim]Gespeichert in: {output_db}[/dim]")

    extractor.close()


def run_extraction(domain, team, apikey, config, env, db_path, databases):
    """Führt Extraktion im non-interactive Mode aus"""
    # Lade config falls angegeben
    if config:
        import yaml
        with open(config, 'r') as f:
            cfg = yaml.safe_load(f)
        env_cfg = cfg.get('environments', {}).get(env, {})
        domain = domain or env_cfg.get('domain')
        team = team or env_cfg.get('workspaceId') or env_cfg.get('teamId')
        apikey = apikey or env_cfg.get('apiKey')

    if not all([domain, team, apikey]):
        console.print("[red]Fehler: domain, team und apikey erforderlich[/red]")
        raise typer.Exit(1)

    client = NinoxAPIClient(domain, team, apikey)
    extractor = NinoxSchemaExtractor(client, db_path)

    with console.status("[bold green]Extrahiere..."):
        stats = extractor.extract_all(databases)

    console.print(f"[green]Fertig:[/green] {stats}")
    extractor.close()


# =============================================================================
# SEARCH Command
# =============================================================================

@app.command()
def search(
    query: Optional[str] = typer.Argument(None, help="Suchbegriff"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i/-I"),
):
    """
    Volltextsuche in Scripts und Formeln.
    """
    if interactive and query is None:
        interactive_search(str(db))
    else:
        if query is None:
            console.print("[red]Fehler: Suchbegriff erforderlich[/red]")
            raise typer.Exit(1)
        run_search(query, str(db))


def interactive_search(db_path: str = DEFAULT_DB):
    """Interaktive Suche"""
    if not db_exists(db_path):
        console.print(f"[red]Datenbank nicht gefunden: {db_path}[/red]")
        return

    extractor = get_extractor(db_path)

    while True:
        console.print("\n[bold]Script-Suche[/bold]\n")

        query = questionary.text(
            "Suchbegriff (leer = zurück):",
            style=custom_style
        ).ask()

        if not query:
            break

        # Filter-Optionen
        add_filter = questionary.confirm(
            "Filter hinzufügen?",
            default=False,
            style=custom_style
        ).ask()

        table_filter = None
        type_filter = None
        limit = 20

        if add_filter:
            # Tabellen laden für Auswahl
            tables = extractor.list_tables()
            table_names = sorted(set(t['name'] for t in tables))

            if table_names:
                table_filter = questionary.autocomplete(
                    "Tabelle (leer = alle):",
                    choices=[''] + table_names,
                    style=custom_style
                ).ask() or None

            # Code-Typen
            cursor = extractor.conn.cursor()
            cursor.execute("SELECT DISTINCT code_type FROM scripts ORDER BY code_type")
            code_types = [row[0] for row in cursor.fetchall()]

            if code_types:
                type_filter = questionary.select(
                    "Code-Typ:",
                    choices=['(alle)'] + code_types,
                    style=custom_style
                ).ask()
                if type_filter == '(alle)':
                    type_filter = None

            limit = int(questionary.text(
                "Max. Ergebnisse:",
                default="20",
                style=custom_style
            ).ask() or "20")

        # Suche durchführen
        with console.status("[bold green]Suche..."):
            results = extractor.search_scripts(
                query,
                table_name=table_filter,
                code_type=type_filter,
                limit=limit
            )

        if not results:
            console.print("[yellow]Keine Treffer gefunden.[/yellow]")
            continue

        # Ergebnisse anzeigen
        display_search_results(results, query)

        # Detail-Ansicht
        if len(results) > 0:
            view_detail = questionary.confirm(
                "Script-Details anzeigen?",
                default=False,
                style=custom_style
            ).ask()

            if view_detail:
                choices = [
                    questionary.Choice(
                        title=f"{i+1}. {r['database_name']}.{r['table_name'] or '(DB)'}.{r['element_name'] or r['code_type']}",
                        value=i
                    )
                    for i, r in enumerate(results)
                ]

                selected = questionary.select(
                    "Script auswählen:",
                    choices=choices,
                    style=custom_style
                ).ask()

                if selected is not None:
                    show_script_detail(results[selected], query)

    extractor.close()


def display_search_results(results: List[Dict], query: str):
    """Zeigt Suchergebnisse an"""
    console.print(f"\n[cyan]{len(results)}[/cyan] Treffer für '[yellow]{query}[/yellow]':\n")

    table = Table(show_header=True, expand=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Ort", style="cyan", no_wrap=True)
    table.add_column("Typ", style="yellow", width=12)
    table.add_column("Vorschau", style="dim", overflow="ellipsis")

    for i, r in enumerate(results, 1):
        loc = f"{r['database_name'][:15]}.{(r['table_name'] or 'DB')[:15]}"
        if r['element_name']:
            loc += f".{r['element_name'][:15]}"

        preview = get_code_preview(r['code'], max_length=60)

        table.add_row(
            str(i),
            loc,
            r['code_type'],
            preview
        )

    console.print(table)


def show_script_detail(script: Dict, highlight_text: str = None):
    """Zeigt Script-Details an"""
    console.print()

    # Header
    loc = f"{script['database_name']} > {script['table_name'] or '(Database)'}"
    if script['element_name']:
        loc += f" > {script['element_name']}"

    console.print(Panel(
        f"[bold]{loc}[/bold]\n"
        f"[dim]Typ: {script['code_type']} | Kategorie: {script['code_category']} | Zeilen: {script['line_count']}[/dim]",
        title="Script Details",
        border_style="cyan"
    ))

    # Code mit Syntax-Highlighting
    syntax = Syntax(
        script['code'],
        "javascript",
        theme="monokai",
        line_numbers=True,
        word_wrap=True
    )
    console.print(syntax)


def run_search(query: str, db_path: str):
    """Führt Suche im non-interactive Mode aus"""
    extractor = get_extractor(db_path)
    results = extractor.search_scripts(query, limit=20)
    display_search_results(results, query)
    extractor.close()


# =============================================================================
# BROWSE Command
# =============================================================================

@app.command()
def browse(
    db: Path = typer.Option(DEFAULT_DB, "--db"),
):
    """
    Interaktiver Browser für Datenbanken und Tabellen.
    """
    interactive_browse(str(db))


def interactive_browse(db_path: str = DEFAULT_DB):
    """Interaktiver Datenbank-Browser"""
    if not db_exists(db_path):
        console.print(f"[red]Datenbank nicht gefunden: {db_path}[/red]")
        return

    extractor = get_extractor(db_path)

    while True:
        # Datenbanken laden
        databases = extractor.list_databases()

        if not databases:
            console.print("[yellow]Keine Datenbanken gefunden.[/yellow]")
            break

        console.print("\n[bold]Datenbank-Browser[/bold]\n")

        # Datenbank auswählen
        db_choices = [
            questionary.Choice(
                title=f"{d['name']} ({d['table_count']} Tabellen, {d['code_count']} Scripts)",
                value=d['id']
            )
            for d in databases
        ]
        db_choices.append(questionary.Choice(title="<< Zurück", value=None))

        selected_db = questionary.select(
            "Datenbank auswählen:",
            choices=db_choices,
            style=custom_style
        ).ask()

        if selected_db is None:
            break

        db_info = next(d for d in databases if d['id'] == selected_db)
        browse_database(extractor, db_info)

    extractor.close()


def browse_database(extractor: NinoxSchemaExtractor, db_info: Dict):
    """Durchsucht eine einzelne Datenbank"""
    while True:
        tables = extractor.list_tables(db_info['id'])

        console.print(f"\n[bold cyan]{db_info['name']}[/bold cyan]\n")

        table_choices = [
            questionary.Choice(
                title=f"{t['name']} ({t['field_count']} Felder)",
                value=t
            )
            for t in tables
        ]
        table_choices.append(questionary.Choice(title="<< Zurück", value=None))

        selected = questionary.select(
            "Tabelle auswählen:",
            choices=table_choices,
            style=custom_style
        ).ask()

        if selected is None:
            break

        browse_table(extractor, db_info, selected)


def browse_table(extractor: NinoxSchemaExtractor, db_info: Dict, table_info: Dict):
    """Zeigt Tabellen-Details"""
    cursor = extractor.conn.cursor()

    while True:
        console.print(f"\n[bold cyan]{db_info['name']} > {table_info['name']}[/bold cyan]\n")

        # Felder laden
        cursor.execute("""
            SELECT * FROM fields
            WHERE database_id = ? AND table_id = ?
            ORDER BY name
        """, (db_info['id'], table_info['table_id']))
        fields = [dict(row) for row in cursor.fetchall()]

        # Scripts laden
        cursor.execute("""
            SELECT * FROM scripts
            WHERE database_id = ? AND table_name = ?
            ORDER BY code_type, element_name
        """, (db_info['id'], table_info['name']))
        scripts = [dict(row) for row in cursor.fetchall()]

        action = questionary.select(
            "Anzeigen:",
            choices=[
                questionary.Choice(f"Felder ({len(fields)})", value="fields"),
                questionary.Choice(f"Scripts ({len(scripts)})", value="scripts"),
                questionary.Choice("Abhängigkeiten", value="deps"),
                questionary.Separator(),
                questionary.Choice("<< Zurück", value=None),
            ],
            style=custom_style
        ).ask()

        if action is None:
            break
        elif action == "fields":
            show_fields(fields)
        elif action == "scripts":
            browse_scripts(scripts)
        elif action == "deps":
            show_table_deps(extractor, table_info['name'])


def show_fields(fields: List[Dict]):
    """Zeigt Felder einer Tabelle"""
    console.print()

    table = Table(show_header=True, title="Felder")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim")
    table.add_column("Typ", style="yellow")
    table.add_column("Referenz", style="green")
    table.add_column("Formel", style="magenta")

    for f in fields:
        ref = f['ref_table_name'] or ""
        formula = "Ja" if f['has_formula'] else ""

        table.add_row(
            f['caption'] or f['name'],
            f['field_id'],
            f['base_type'] or "",
            ref,
            formula
        )

    console.print(table)

    questionary.press_any_key_to_continue(
        "Weiter mit beliebiger Taste...",
        style=custom_style
    ).ask()


def browse_scripts(scripts: List[Dict]):
    """Durchsucht Scripts einer Tabelle"""
    if not scripts:
        console.print("[yellow]Keine Scripts vorhanden.[/yellow]")
        return

    while True:
        choices = [
            questionary.Choice(
                title=f"{s['element_name'] or '(Tabelle)'} - {s['code_type']} ({s['line_count']} Zeilen)",
                value=s
            )
            for s in scripts
        ]
        choices.append(questionary.Choice(title="<< Zurück", value=None))

        selected = questionary.select(
            "Script auswählen:",
            choices=choices,
            style=custom_style
        ).ask()

        if selected is None:
            break

        show_script_detail(selected)

        questionary.press_any_key_to_continue(
            "Weiter mit beliebiger Taste...",
            style=custom_style
        ).ask()


# =============================================================================
# DEPS Command
# =============================================================================

@app.command()
def deps(
    table_name: Optional[str] = typer.Argument(None, help="Tabellenname"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
):
    """
    Zeigt Abhängigkeiten einer Tabelle.
    """
    if table_name is None:
        interactive_deps(str(db))
    else:
        show_table_deps_cli(table_name, str(db))


def interactive_deps(db_path: str = DEFAULT_DB):
    """Interaktive Abhängigkeiten-Anzeige"""
    if not db_exists(db_path):
        console.print(f"[red]Datenbank nicht gefunden: {db_path}[/red]")
        return

    extractor = get_extractor(db_path)

    # Tabellen laden
    tables = extractor.list_tables()
    table_names = sorted(set(t['name'] for t in tables))

    if not table_names:
        console.print("[yellow]Keine Tabellen gefunden.[/yellow]")
        extractor.close()
        return

    console.print("\n[bold]Abhängigkeiten anzeigen[/bold]\n")

    table_name = questionary.autocomplete(
        "Tabelle auswählen:",
        choices=table_names,
        style=custom_style
    ).ask()

    if table_name:
        show_table_deps(extractor, table_name)

    extractor.close()


def show_table_deps(extractor: NinoxSchemaExtractor, table_name: str):
    """Zeigt Tabellen-Abhängigkeiten"""
    deps_data = extractor.get_table_dependencies(table_name)

    console.print(f"\n[bold]Abhängigkeiten für '[cyan]{table_name}[/cyan]'[/bold]\n")

    # Tree-Visualisierung
    tree = Tree(f"[bold cyan]{table_name}[/bold cyan]")

    # Ausgehende Referenzen
    refs_branch = tree.add("[green]→ Referenziert[/green]")
    if deps_data['references']:
        for ref in deps_data['references']:
            label = f"{ref['source_field_name']} → [yellow]{ref['target_table_name']}[/yellow]"
            if ref['is_composition']:
                label += " [dim](Composition)[/dim]"
            refs_branch.add(label)
    else:
        refs_branch.add("[dim](keine)[/dim]")

    # Eingehende Referenzen
    back_branch = tree.add("[blue]← Referenziert von[/blue]")
    if deps_data['referenced_by']:
        for ref in deps_data['referenced_by']:
            back_branch.add(f"[yellow]{ref['source_table_name']}[/yellow].{ref['source_field_name']}")
    else:
        back_branch.add("[dim](keine)[/dim]")

    # Formel-Referenzen
    if deps_data['formula_references']:
        formula_branch = tree.add(f"[magenta]Formel-Referenzen ({len(deps_data['formula_references'])})[/magenta]")
        for ref in deps_data['formula_references'][:5]:
            formula_branch.add(f"{ref['source_table_name']}.{ref['source_field_name']} [dim]({ref['found_in_code_type']})[/dim]")
        if len(deps_data['formula_references']) > 5:
            formula_branch.add(f"[dim]... und {len(deps_data['formula_references']) - 5} weitere[/dim]")

    console.print(tree)

    questionary.press_any_key_to_continue(
        "\nWeiter mit beliebiger Taste...",
        style=custom_style
    ).ask()


def show_table_deps_cli(table_name: str, db_path: str):
    """CLI-Version der Abhängigkeiten-Anzeige"""
    extractor = get_extractor(db_path)
    show_table_deps(extractor, table_name)
    extractor.close()


# =============================================================================
# STATS Command
# =============================================================================

@app.command()
def stats(
    db: Path = typer.Option(DEFAULT_DB, "--db"),
):
    """
    Zeigt Statistiken über die extrahierten Daten.
    """
    show_stats(str(db))


def show_stats(db_path: str = DEFAULT_DB):
    """Zeigt Statistiken"""
    if not db_exists(db_path):
        console.print(f"[red]Datenbank nicht gefunden: {db_path}[/red]")
        return

    extractor = get_extractor(db_path)
    stats_data = extractor.get_statistics()

    console.print("\n[bold]Ninox Schema Statistiken[/bold]\n")

    # Hauptzahlen als Panel
    main_stats = Table(show_header=False, box=None, padding=(0, 2))
    main_stats.add_column("", style="cyan", width=15)
    main_stats.add_column("", justify="right", style="bold white")

    main_stats.add_row("Datenbanken", str(stats_data['databases_count']))
    main_stats.add_row("Tabellen", str(stats_data['tables_count']))
    main_stats.add_row("Felder", str(stats_data['fields_count']))
    main_stats.add_row("Verknüpfungen", str(stats_data['relationships_count']))
    main_stats.add_row("Scripts", str(stats_data['scripts_count']))

    console.print(Panel(main_stats, title="Übersicht", border_style="blue"))

    # Scripts nach Typ
    console.print("\n[bold]Scripts nach Typ[/bold]")
    for typ, count in list(stats_data['scripts_by_type'].items())[:8]:
        bar_width = min(count // 5, 40)
        bar = "[cyan]" + "█" * bar_width + "[/cyan]"
        console.print(f"  {typ:20} {bar} {count}")

    # Top Tabellen
    console.print("\n[bold]Top 5 Tabellen (nach Scripts)[/bold]")
    for i, (table_name, count) in enumerate(list(stats_data['top_tables_by_scripts'].items())[:5], 1):
        console.print(f"  {i}. [cyan]{table_name}[/cyan]: {count}")

    extractor.close()

    questionary.press_any_key_to_continue(
        "\nWeiter mit beliebiger Taste...",
        style=custom_style
    ).ask()


# =============================================================================
# EXPORT Command
# =============================================================================

@app.command("export")
def export_cmd(
    output: Optional[Path] = typer.Argument(None, help="Ausgabedatei"),
    db: Path = typer.Option(DEFAULT_DB, "--db"),
    format: Optional[str] = typer.Option(None, "--format", "-f",
                                          help="Format: json, html, md"),
):
    """
    Exportiert Daten in verschiedene Formate.
    """
    if output is None or format is None:
        interactive_export(str(db))
    else:
        run_export(str(output), format, str(db))


def interactive_export(db_path: str = DEFAULT_DB):
    """Interaktiver Export"""
    if not db_exists(db_path):
        console.print(f"[red]Datenbank nicht gefunden: {db_path}[/red]")
        return

    console.print("\n[bold]Daten exportieren[/bold]\n")

    # Format auswählen
    format_choice = questionary.select(
        "Export-Format:",
        choices=[
            questionary.Choice("JSON (Strukturierte Daten)", value="json"),
            questionary.Choice("HTML (Mit Syntax-Highlighting)", value="html"),
            questionary.Choice("Markdown (Dokumentation)", value="md"),
        ],
        style=custom_style
    ).ask()

    if not format_choice:
        return

    # Standard-Dateiname
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"ninox_export_{timestamp}.{format_choice}"

    output_path = questionary.text(
        "Ausgabedatei:",
        default=default_name,
        style=custom_style
    ).ask()

    if not output_path:
        return

    # Optional: Datenbank-Filter
    extractor = get_extractor(db_path)
    databases = extractor.list_databases()

    db_filter = None
    if len(databases) > 1:
        filter_db = questionary.confirm(
            "Auf eine Datenbank beschränken?",
            default=False,
            style=custom_style
        ).ask()

        if filter_db:
            db_filter = questionary.select(
                "Datenbank auswählen:",
                choices=[d['name'] for d in databases],
                style=custom_style
            ).ask()

    # Export durchführen
    with console.status(f"[bold green]Exportiere als {format_choice.upper()}..."):
        if format_choice == "json":
            extractor.export_to_json(output_path)
        elif format_choice == "html":
            extractor.export_scripts_to_html(output_path, db_filter)
        elif format_choice == "md":
            extractor.export_to_markdown(output_path, db_filter)

    console.print(f"\n[green]Export erfolgreich:[/green] {output_path}")
    extractor.close()


def run_export(output: str, format: str, db_path: str):
    """Führt Export im non-interactive Mode aus"""
    extractor = get_extractor(db_path)

    if format == "json":
        extractor.export_to_json(output)
    elif format == "html":
        extractor.export_scripts_to_html(output)
    elif format == "md":
        extractor.export_to_markdown(output)
    else:
        console.print(f"[red]Unbekanntes Format: {format}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Exportiert:[/green] {output}")
    extractor.close()


# =============================================================================
# VERSION Command
# =============================================================================

@app.command()
def version():
    """Zeigt die Version an."""
    console.print(Panel.fit(
        "[bold cyan]Ninox Interactive CLI[/bold cyan]\n"
        "Version 1.0.0\n\n"
        "[dim]Kombiniert Typer + Rich + questionary[/dim]\n"
        "[dim]für eine moderne CLI-Erfahrung[/dim]",
        border_style="cyan"
    ))


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    app()
