#!/usr/bin/env python3
"""
Ninox Database Viewer - Textual TUI
"""

import sqlite3
import sys
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Input, DataTable,
    Label, ListView, ListItem, TextArea, TabbedContent, TabPane
)
from textual.screen import Screen, ModalScreen
from textual import events

# Pfade
SCRIPT_DIR = Path(__file__).parent
DEFAULT_DB = SCRIPT_DIR / "ninoxstructur.db"
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
EXTRACTOR = SCRIPT_DIR / "ninox_api_extractor.py"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return config.get('environments', {}) if config else {}
    except:
        return {}


def save_config(environments: dict) -> bool:
    try:
        import yaml
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump({'environments': environments}, f, default_flow_style=False, allow_unicode=True)
        return True
    except:
        return False


class Database:
    """SQLite Datenbank-Wrapper"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self._connect()

    def _connect(self):
        if self.db_path.exists():
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row

    def reconnect(self):
        if self.conn:
            self.conn.close()
        self._connect()

    def close(self):
        if self.conn:
            self.conn.close()

    def get_stats(self) -> dict:
        stats = {'databases': 0, 'tables': 0, 'fields': 0, 'scripts': 0, 'deps': 0}
        if not self.conn:
            return stats
        cur = self.conn.cursor()
        for key, table in [('databases', 'databases'), ('tables', 'tables'),
                           ('fields', 'fields'), ('scripts', 'scripts'),
                           ('deps', 'script_dependencies')]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                stats[key] = cur.fetchone()[0]
            except:
                pass
        return stats

    def search_scripts(self, query: str, limit: int = 100) -> list:
        if not self.conn:
            return []
        cur = self.conn.cursor()

        # AND/OR parsen
        import re
        upper = query.upper()
        if ' AND ' in upper:
            parts = re.split(r'\s+AND\s+', query, flags=re.IGNORECASE)
            terms, operator = [p.strip() for p in parts], 'AND'
        elif ' OR ' in upper:
            parts = re.split(r'\s+OR\s+', query, flags=re.IGNORECASE)
            terms, operator = [p.strip() for p in parts], 'OR'
        else:
            terms, operator = [query.strip()], 'AND'

        sql = """SELECT id, database_name, table_name, element_name,
                        code_type, code, line_count FROM scripts WHERE 1=1"""
        params = []

        if operator == 'AND':
            for term in terms:
                sql += " AND (code LIKE ? OR element_name LIKE ? OR table_name LIKE ?)"
                params.extend([f'%{term}%'] * 3)
        else:
            conditions = []
            for term in terms:
                conditions.append("(code LIKE ? OR element_name LIKE ? OR table_name LIKE ?)")
                params.extend([f'%{term}%'] * 3)
            sql += f" AND ({' OR '.join(conditions)})"

        sql += f" ORDER BY database_name, table_name LIMIT {limit}"
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def get_script_types(self) -> list:
        if not self.conn:
            return []
        cur = self.conn.cursor()
        cur.execute("""SELECT code_type, COUNT(*) as cnt
                       FROM scripts GROUP BY code_type ORDER BY cnt DESC""")
        return [dict(row) for row in cur.fetchall()]

    def get_scripts_by_type(self, code_type: str, limit: int = 100) -> list:
        if not self.conn:
            return []
        cur = self.conn.cursor()
        cur.execute("""SELECT id, database_name, table_name, element_name,
                       code_type, code, line_count FROM scripts
                       WHERE code_type = ? LIMIT ?""", (code_type, limit))
        return [dict(row) for row in cur.fetchall()]

    def get_databases(self) -> list:
        if not self.conn:
            return []
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, table_count, code_count FROM databases ORDER BY name")
        return [dict(row) for row in cur.fetchall()]

    def get_tables(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        cur = self.conn.cursor()
        cur.execute("""SELECT t.name, t.caption, t.field_count, d.name as db_name
                       FROM tables t JOIN databases d ON t.database_id = d.id
                       ORDER BY d.name, t.name LIMIT ?""", (limit,))
        return [dict(row) for row in cur.fetchall()]


# ─────────────────────────────────────────────────────────────
# SCREENS
# ─────────────────────────────────────────────────────────────

class ScriptDetailScreen(ModalScreen):
    """Modal für Script-Details"""

    BINDINGS = [
        Binding("escape", "dismiss", "Schließen"),
        Binding("q", "dismiss", "Schließen"),
    ]

    CSS = """
    ScriptDetailScreen {
        align: center middle;
    }

    ScriptDetailScreen > Container {
        width: 90%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    #script-header {
        height: 4;
        padding: 0 1;
    }

    #script-code {
        border: solid $primary-lighten-2;
    }
    """

    def __init__(self, script: dict):
        super().__init__()
        self.script = script

    def compose(self) -> ComposeResult:
        code = (self.script.get('code') or '').replace('\\n', '\n').replace('\\t', '\t')

        with Container():
            yield Static(
                f"[bold]{self.script.get('table_name', '')}[/] › {self.script.get('element_name', '')}\n"
                f"[dim]{self.script.get('database_name', '')} | {self.script.get('code_type', '')} | "
                f"{self.script.get('line_count', 0)} Zeilen[/]",
                id="script-header"
            )
            yield TextArea(code, read_only=True, id="script-code", show_line_numbers=True)


class ExtractScreen(ModalScreen):
    """Modal für Extraktion"""

    BINDINGS = [
        Binding("escape", "dismiss", "Schließen"),
    ]

    CSS = """
    ExtractScreen {
        align: center middle;
    }

    ExtractScreen > Container {
        width: 60;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #extract-title {
        text-align: center;
        text-style: bold;
        padding: 1;
    }

    #extract-log {
        height: auto;
        max-height: 15;
        border: solid $primary-lighten-2;
        padding: 1;
        margin-top: 1;
    }

    .env-button {
        margin: 0 1 1 1;
    }
    """

    def __init__(self, environments: dict, db_path: Path, on_complete: callable):
        super().__init__()
        self.environments = environments
        self.db_path = db_path
        self.on_complete = on_complete
        self.log_text = ""

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Daten aus Ninox abrufen", id="extract-title")

            for name in self.environments.keys():
                env = self.environments[name]
                yield Button(
                    f"{name} - {env.get('teamName', '')}",
                    id=f"env-{name}",
                    classes="env-button"
                )

            yield Button("Alle Teams", id="env-all", variant="primary", classes="env-button")
            yield Static("", id="extract-log")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "env-all":
            self.run_extraction(list(self.environments.keys()))
        elif button_id.startswith("env-"):
            env_name = button_id[4:]
            self.run_extraction([env_name])

    def _log(self, text: str):
        """Fügt Text zum Log hinzu und aktualisiert das Widget"""
        self.log_text += text
        self.query_one("#extract-log", Static).update(self.log_text)

    def run_extraction(self, env_names: list):
        self.log_text = "[bold]Extraktion gestartet...[/]\n"
        self._log("")

        for env_name in env_names:
            self._log(f"\n► Extrahiere [bold]{env_name}[/]...")

            cmd = [sys.executable, str(EXTRACTOR), 'extract',
                   '--config', str(CONFIG_FILE), '--env', env_name,
                   '--db', str(self.db_path)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
                if result.returncode == 0:
                    self._log(" [green]✓[/]")
                else:
                    self._log(f" [red]✗[/]\n{result.stderr[:200]}")
            except Exception as e:
                self._log(f" [red]✗ {e}[/]")

        self._log("\n\n[dim]ESC zum Schließen[/]")
        self.on_complete()


# ─────────────────────────────────────────────────────────────
# HAUPTANWENDUNG
# ─────────────────────────────────────────────────────────────

class NinoxViewer(App):
    """Ninox Database Viewer - Textual App"""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        height: 100%;
    }

    #sidebar {
        width: 25;
        border-right: solid $primary;
        padding: 1;
    }

    #sidebar-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        color: $text;
    }

    #content {
        padding: 1 2;
    }

    #stats-panel {
        height: 5;
        border: solid $primary-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }

    #search-box {
        height: 3;
        margin-bottom: 1;
    }

    #search-input {
        width: 100%;
    }

    #results-table {
        height: 1fr;
        border: solid $primary-lighten-2;
    }

    .nav-button {
        width: 100%;
        margin-bottom: 1;
    }

    #code-preview {
        height: 10;
        border: solid $accent;
        margin-top: 1;
        padding: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Beenden"),
        Binding("s", "focus_search", "Suche"),
        Binding("r", "refresh", "Refresh"),
        Binding("e", "extract", "Extrahieren"),
        Binding("d", "show_databases", "Datenbanken"),
        Binding("t", "show_tables", "Tabellen"),
        Binding("c", "show_types", "Code-Typen"),
        Binding("escape", "clear_selection", "Abbrechen"),
    ]

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path
        self.db = Database(db_path)
        self.environments = load_config()
        self.current_results = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main-container"):
            with Vertical(id="sidebar"):
                yield Static("NINOX VIEWER", id="sidebar-title")
                yield Button("🔍 Suche", id="btn-search", classes="nav-button")
                yield Button("📝 Scripts", id="btn-scripts", classes="nav-button")
                yield Button("🗄️ Datenbanken", id="btn-databases", classes="nav-button")
                yield Button("📋 Tabellen", id="btn-tables", classes="nav-button")
                yield Button("⬇️ Extrahieren", id="btn-extract", classes="nav-button", variant="primary")

            with Vertical(id="content"):
                yield Static(self._get_stats_text(), id="stats-panel")

                with Horizontal(id="search-box"):
                    yield Input(placeholder="Suche... (AND/OR unterstützt)", id="search-input")

                yield DataTable(id="results-table", cursor_type="row")
                yield Static("", id="code-preview")

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Nr", "Tabelle", "Element", "Typ", "Zeilen")
        self._show_script_types()

    def _get_stats_text(self) -> str:
        stats = self.db.get_stats()
        return (
            f"[bold]Statistik:[/] {stats['databases']} Datenbanken │ "
            f"{stats['tables']} Tabellen │ {stats['scripts']} Scripts │ "
            f"{stats['fields']} Felder"
        )

    def _update_stats(self) -> None:
        self.query_one("#stats-panel", Static).update(self._get_stats_text())

    def _clear_table(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()

    def _show_results(self, results: list, title: str = "Ergebnisse") -> None:
        self.current_results = results
        table = self.query_one("#results-table", DataTable)
        table.clear()

        for i, row in enumerate(results, 1):
            table.add_row(
                str(i),
                row.get('table_name') or '(global)',
                row.get('element_name') or '-',
                row.get('code_type', ''),
                str(row.get('line_count', 0)),
                key=str(i-1)
            )

        self.query_one("#code-preview", Static).update(f"[dim]{len(results)} Ergebnisse[/]")

    def _show_script_types(self) -> None:
        types = self.db.get_script_types()
        self.current_results = [{'code_type': t['code_type'], 'cnt': t['cnt']} for t in types]

        table = self.query_one("#results-table", DataTable)
        table.clear()

        for i, t in enumerate(types, 1):
            bar = '█' * min(t['cnt'] // 10, 20)
            table.add_row(
                str(i),
                t['code_type'],
                str(t['cnt']),
                bar,
                "",
                key=f"type-{i-1}"
            )

        self.query_one("#code-preview", Static).update(
            "[dim]Wähle einen Code-Typ um Scripts anzuzeigen[/]"
        )

    def _show_databases_list(self) -> None:
        dbs = self.db.get_databases()
        self.current_results = dbs

        table = self.query_one("#results-table", DataTable)
        table.clear()

        for i, db in enumerate(dbs, 1):
            table.add_row(
                str(i),
                db['name'],
                f"{db['table_count']} Tab.",
                f"{db['code_count']} Scripts",
                "",
                key=f"db-{i-1}"
            )

        self.query_one("#code-preview", Static).update(f"[dim]{len(dbs)} Datenbanken[/]")

    def _show_tables_list(self) -> None:
        tables = self.db.get_tables()
        self.current_results = tables

        table = self.query_one("#results-table", DataTable)
        table.clear()

        for i, t in enumerate(tables, 1):
            caption = t.get('caption') or ''
            if caption == t['name']:
                caption = ''
            table.add_row(
                str(i),
                t['db_name'],
                t['name'],
                caption[:20],
                f"{t['field_count']} F.",
                key=f"tbl-{i-1}"
            )

        self.query_one("#code-preview", Static).update(f"[dim]{len(tables)} Tabellen[/]")

    # ─────────────────────────────────────────────────────────────
    # EVENT HANDLER
    # ─────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "btn-search":
            self.query_one("#search-input", Input).focus()
        elif button_id == "btn-scripts":
            self._show_script_types()
        elif button_id == "btn-databases":
            self._show_databases_list()
        elif button_id == "btn-tables":
            self._show_tables_list()
        elif button_id == "btn-extract":
            self.action_extract()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            query = event.value.strip()
            if query:
                results = self.db.search_scripts(query)
                self._show_results(results, f"Suche: {query}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self.current_results:
            return

        key = event.row_key.value

        # Code-Typ ausgewählt?
        if key and key.startswith("type-"):
            idx = int(key.split("-")[1])
            if idx < len(self.current_results):
                code_type = self.current_results[idx].get('code_type')
                if code_type:
                    results = self.db.get_scripts_by_type(code_type)
                    self._show_results(results, f"Typ: {code_type}")
            return

        # Script ausgewählt - zeige Details
        try:
            idx = int(key) if key else event.cursor_row
            if 0 <= idx < len(self.current_results):
                script = self.current_results[idx]
                if 'code' in script:
                    self.push_screen(ScriptDetailScreen(script))
        except (ValueError, TypeError):
            pass

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Zeigt Code-Vorschau beim Navigieren"""
        if not self.current_results:
            return

        try:
            key = event.row_key.value if event.row_key else None
            if key and key.startswith(("type-", "db-", "tbl-")):
                return

            idx = int(key) if key else event.cursor_row
            if 0 <= idx < len(self.current_results):
                script = self.current_results[idx]
                code = (script.get('code') or '').replace('\\n', '\n').replace('\\t', '\t')
                lines = [l for l in code.split('\n') if l.strip()][:3]
                preview = '\n'.join(lines)
                if len(code.split('\n')) > 3:
                    preview += f"\n[dim]... +{len(code.split(chr(10)))-3} Zeilen[/]"
                self.query_one("#code-preview", Static).update(preview)
        except (ValueError, TypeError):
            pass

    # ─────────────────────────────────────────────────────────────
    # ACTIONS
    # ─────────────────────────────────────────────────────────────

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_refresh(self) -> None:
        self.db.reconnect()
        self._update_stats()
        self._show_script_types()
        self.notify("Daten aktualisiert", timeout=2)

    def action_extract(self) -> None:
        if not self.environments:
            self.notify("Keine Environments in config.yaml", severity="error")
            return

        def on_complete():
            self.db.reconnect()
            self._update_stats()

        self.push_screen(ExtractScreen(self.environments, self.db_path, on_complete))

    def action_show_databases(self) -> None:
        self._show_databases_list()

    def action_show_tables(self) -> None:
        self._show_tables_list()

    def action_show_types(self) -> None:
        self._show_script_types()

    def action_clear_selection(self) -> None:
        self._show_script_types()


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    app = NinoxViewer(db_path)
    app.run()


if __name__ == "__main__":
    main()
