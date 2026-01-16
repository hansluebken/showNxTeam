#!/usr/bin/env python3
"""
Ninox TUI - Terminal User Interface
====================================
Moderne Terminal-Anwendung mit Textual.

Features:
- Vollständige UI mit Widgets
- Keyboard & Mouse Support
- CSS-basiertes Styling
- Syntax-Highlighting für Code
- Durchsuchbare Tabellen

Verwendung:
    ./ninox_tui.py [database.db]
"""

import sys
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Header, Footer, Static, Button, Input, Label,
    DataTable, Tree, TabbedContent, TabPane,
    ListView, ListItem, Markdown, TextArea,
    LoadingIndicator, Rule, Placeholder,
)
from textual.widget import Widget
from rich.syntax import Syntax
from rich.text import Text
from rich.panel import Panel

# Import aus bestehendem Modul
from ninox_api_extractor import (
    NinoxSchemaExtractor,
    get_code_preview,
)

DEFAULT_DB = "ninox_schema.db"


# =============================================================================
# Custom Widgets
# =============================================================================

class CodeViewer(Static):
    """Widget für Code mit Syntax-Highlighting"""

    DEFAULT_CSS = """
    CodeViewer {
        height: auto;
        padding: 1;
        background: $surface;
        border: solid $primary;
    }
    """

    def __init__(self, code: str = "", language: str = "javascript", **kwargs):
        super().__init__(**kwargs)
        self._code = code
        self._language = language

    def update_code(self, code: str, title: str = ""):
        """Aktualisiert den angezeigten Code"""
        self._code = code
        syntax = Syntax(
            code or "// Kein Code",
            self._language,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.update(Panel(syntax, title=title, border_style="cyan"))


class StatsPanel(Static):
    """Widget für Statistiken"""

    DEFAULT_CSS = """
    StatsPanel {
        height: auto;
        padding: 1;
        background: $surface;
        border: solid $accent;
    }
    """

    def update_stats(self, stats: Dict[str, Any]):
        """Aktualisiert die Statistiken"""
        text = Text()
        text.append("📊 Statistiken\n\n", style="bold cyan")
        text.append(f"Datenbanken:   {stats.get('databases_count', 0)}\n")
        text.append(f"Tabellen:      {stats.get('tables_count', 0)}\n")
        text.append(f"Felder:        {stats.get('fields_count', 0)}\n")
        text.append(f"Verknüpfungen: {stats.get('relationships_count', 0)}\n")
        text.append(f"Scripts:       {stats.get('scripts_count', 0)}\n")
        self.update(text)


# =============================================================================
# Search Screen (Modal)
# =============================================================================

class SearchScreen(ModalScreen[Optional[Dict]]):
    """Modal-Screen für die Suche"""

    BINDINGS = [
        Binding("escape", "cancel", "Abbrechen"),
        Binding("enter", "search", "Suchen"),
    ]

    DEFAULT_CSS = """
    SearchScreen {
        align: center middle;
    }

    SearchScreen > Vertical {
        width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    SearchScreen Input {
        margin: 1 0;
    }

    SearchScreen #results {
        height: auto;
        max-height: 20;
        margin: 1 0;
    }

    SearchScreen DataTable {
        height: auto;
        max-height: 15;
    }

    SearchScreen .buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    SearchScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, extractor: NinoxSchemaExtractor):
        super().__init__()
        self.extractor = extractor
        self.results = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("🔍 Script-Suche", classes="title")
            yield Input(placeholder="Suchbegriff eingeben...", id="search-input")
            yield Static("", id="result-count")
            yield DataTable(id="results")
            with Horizontal(classes="buttons"):
                yield Button("Suchen", variant="primary", id="btn-search")
                yield Button("Abbrechen", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns("Ort", "Typ", "Vorschau")
        table.cursor_type = "row"
        self.query_one("#search-input", Input).focus()

    @on(Button.Pressed, "#btn-search")
    @on(Input.Submitted)
    def do_search(self) -> None:
        query = self.query_one("#search-input", Input).value
        if not query:
            return

        self.results = self.extractor.search_scripts(query, limit=50)

        table = self.query_one("#results", DataTable)
        table.clear()

        count_label = self.query_one("#result-count", Static)
        count_label.update(f"[cyan]{len(self.results)}[/cyan] Treffer")

        for r in self.results:
            loc = f"{r['database_name'][:20]}.{(r['table_name'] or 'DB')[:15]}"
            if r['element_name']:
                loc += f".{r['element_name'][:10]}"
            preview = get_code_preview(r['code'], 40)
            table.add_row(loc, r['code_type'], preview)

    @on(Button.Pressed, "#btn-cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and self.results:
            idx = event.row_key.value
            if isinstance(idx, int) and idx < len(self.results):
                self.dismiss(self.results[idx])


# =============================================================================
# Main Application
# =============================================================================

class NinoxTUI(App):
    """Ninox Terminal User Interface"""

    TITLE = "Ninox Schema Explorer"
    SUB_TITLE = "Terminal UI"

    CSS = """
    /* Layout */
    #main-container {
        layout: horizontal;
    }

    #sidebar {
        width: 35;
        height: 100%;
        background: $surface;
        border-right: solid $primary;
    }

    #content {
        width: 1fr;
        height: 100%;
    }

    /* Sidebar */
    #sidebar-title {
        text-align: center;
        text-style: bold;
        color: $text;
        background: $primary;
        padding: 1;
    }

    #db-tree {
        height: 1fr;
        scrollbar-gutter: stable;
    }

    #stats-panel {
        height: auto;
        margin: 1;
    }

    /* Content Area */
    #content-header {
        height: 3;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #content-header Label {
        text-style: bold;
        padding: 1;
    }

    #tab-content {
        height: 1fr;
    }

    /* Tables */
    DataTable {
        height: 1fr;
    }

    DataTable > .datatable--header {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    /* Code Viewer */
    #code-container {
        height: 1fr;
        padding: 1;
    }

    #code-viewer {
        height: 1fr;
    }

    /* Info Panel */
    #info-panel {
        height: auto;
        padding: 1;
        background: $surface;
        border: solid $accent;
        margin: 1;
    }

    /* Welcome Screen */
    #welcome {
        align: center middle;
        height: 100%;
    }

    #welcome-box {
        width: 60;
        height: auto;
        padding: 2 4;
        background: $surface;
        border: double $primary;
    }

    #welcome-box Static {
        text-align: center;
        margin: 1 0;
    }

    /* No Data */
    .no-data {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    /* Script List */
    #script-list {
        height: 1fr;
    }

    .script-item {
        padding: 0 1;
    }

    .script-item:hover {
        background: $primary 20%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Beenden"),
        Binding("s", "search", "Suchen"),
        Binding("r", "refresh", "Aktualisieren"),
        Binding("f", "toggle_sidebar", "Sidebar"),
        Binding("1", "tab_fields", "Felder"),
        Binding("2", "tab_scripts", "Scripts"),
        Binding("3", "tab_deps", "Abhängigkeiten"),
        Binding("?", "help", "Hilfe"),
    ]

    def __init__(self, db_path: str = DEFAULT_DB):
        super().__init__()
        self.db_path = db_path
        self.extractor: Optional[NinoxSchemaExtractor] = None
        self.current_db: Optional[Dict] = None
        self.current_table: Optional[Dict] = None
        self.current_script: Optional[Dict] = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            # Sidebar
            with Vertical(id="sidebar"):
                yield Static("📁 Datenbanken", id="sidebar-title")
                yield Tree("Datenbanken", id="db-tree")
                yield StatsPanel(id="stats-panel")

            # Main Content
            with Vertical(id="content"):
                with Horizontal(id="content-header"):
                    yield Label("Willkommen", id="breadcrumb")

                with TabbedContent(id="tab-content"):
                    with TabPane("Felder", id="tab-fields"):
                        yield DataTable(id="fields-table")

                    with TabPane("Scripts", id="tab-scripts"):
                        with Horizontal():
                            with Vertical(id="script-list-container"):
                                yield DataTable(id="scripts-table")
                            with Vertical(id="code-container"):
                                yield CodeViewer(id="code-viewer")

                    with TabPane("Abhängigkeiten", id="tab-deps"):
                        yield DataTable(id="deps-table")

        yield Footer()

    def on_mount(self) -> None:
        """Wird beim Start aufgerufen"""
        self.load_database()

    def load_database(self) -> None:
        """Lädt die SQLite-Datenbank"""
        if not Path(self.db_path).exists():
            self.notify(f"Datenbank nicht gefunden: {self.db_path}", severity="error")
            return

        try:
            self.extractor = NinoxSchemaExtractor(None, self.db_path)
            self.extractor.conn = sqlite3.connect(self.db_path)
            self.extractor.conn.row_factory = sqlite3.Row
            self.populate_tree()
            self.update_stats()
            self.notify(f"Geladen: {self.db_path}")
        except Exception as e:
            self.notify(f"Fehler: {e}", severity="error")

    def populate_tree(self) -> None:
        """Füllt den Datenbank-Baum"""
        if not self.extractor:
            return

        tree = self.query_one("#db-tree", Tree)
        tree.clear()
        tree.root.expand()

        databases = self.extractor.list_databases()

        for db in databases:
            db_node = tree.root.add(
                f"📁 {db['name']} ({db['table_count']})",
                data={"type": "database", "data": db}
            )

            tables = self.extractor.list_tables(db['id'])
            for table in tables:
                db_node.add_leaf(
                    f"📋 {table['name']} ({table['field_count']})",
                    data={"type": "table", "data": table, "db": db}
                )

    def update_stats(self) -> None:
        """Aktualisiert das Statistik-Panel"""
        if not self.extractor:
            return

        stats = self.extractor.get_statistics()
        panel = self.query_one("#stats-panel", StatsPanel)
        panel.update_stats(stats)

    @on(Tree.NodeSelected)
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Handler für Baum-Auswahl"""
        node_data = event.node.data
        if not node_data:
            return

        if node_data["type"] == "database":
            self.current_db = node_data["data"]
            self.current_table = None
            self.update_breadcrumb(self.current_db['name'])
            self.clear_tables()

        elif node_data["type"] == "table":
            self.current_db = node_data["db"]
            self.current_table = node_data["data"]
            self.update_breadcrumb(
                f"{self.current_db['name']} > {self.current_table['name']}"
            )
            self.load_table_data()

    def update_breadcrumb(self, text: str) -> None:
        """Aktualisiert die Breadcrumb-Anzeige"""
        label = self.query_one("#breadcrumb", Label)
        label.update(f"📍 {text}")

    def clear_tables(self) -> None:
        """Leert alle Tabellen"""
        for table_id in ["#fields-table", "#scripts-table", "#deps-table"]:
            table = self.query_one(table_id, DataTable)
            table.clear(columns=True)

        viewer = self.query_one("#code-viewer", CodeViewer)
        viewer.update_code("", "Code")

    def load_table_data(self) -> None:
        """Lädt Daten für die ausgewählte Tabelle"""
        if not self.extractor or not self.current_table or not self.current_db:
            return

        self.load_fields()
        self.load_scripts()
        self.load_dependencies()

    def load_fields(self) -> None:
        """Lädt Felder"""
        cursor = self.extractor.conn.cursor()
        cursor.execute("""
            SELECT * FROM fields
            WHERE database_id = ? AND table_id = ?
            ORDER BY name
        """, (self.current_db['id'], self.current_table['table_id']))

        fields = [dict(row) for row in cursor.fetchall()]

        table = self.query_one("#fields-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "ID", "Typ", "Referenz", "Formel")
        table.cursor_type = "row"

        for f in fields:
            table.add_row(
                f['caption'] or f['name'],
                f['field_id'],
                f['base_type'] or "",
                f['ref_table_name'] or "",
                "✓" if f['has_formula'] else "",
            )

    def load_scripts(self) -> None:
        """Lädt Scripts"""
        cursor = self.extractor.conn.cursor()
        cursor.execute("""
            SELECT * FROM scripts
            WHERE database_id = ? AND table_name = ?
            ORDER BY code_type, element_name
        """, (self.current_db['id'], self.current_table['name']))

        self.scripts = [dict(row) for row in cursor.fetchall()]

        table = self.query_one("#scripts-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Element", "Typ", "Zeilen")
        table.cursor_type = "row"

        for s in self.scripts:
            table.add_row(
                s['element_name'] or "(Tabelle)",
                s['code_type'],
                str(s['line_count']),
            )

    def load_dependencies(self) -> None:
        """Lädt Abhängigkeiten"""
        if not self.current_table:
            return

        deps = self.extractor.get_table_dependencies(self.current_table['name'])

        table = self.query_one("#deps-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Richtung", "Feld", "Ziel/Quelle", "Typ")
        table.cursor_type = "row"

        for ref in deps['references']:
            table.add_row(
                "→",
                ref['source_field_name'],
                ref['target_table_name'],
                ref['relationship_type']
            )

        for ref in deps['referenced_by']:
            table.add_row(
                "←",
                ref['source_field_name'],
                ref['source_table_name'],
                ref['relationship_type']
            )

    @on(DataTable.RowSelected, "#scripts-table")
    def on_script_selected(self, event: DataTable.RowSelected) -> None:
        """Handler für Script-Auswahl"""
        if not hasattr(self, 'scripts') or not self.scripts:
            return

        row_idx = event.cursor_row
        if row_idx < len(self.scripts):
            script = self.scripts[row_idx]
            self.current_script = script

            title = f"{script['element_name'] or 'Tabelle'} - {script['code_type']}"
            viewer = self.query_one("#code-viewer", CodeViewer)
            viewer.update_code(script['code'], title)

    def action_search(self) -> None:
        """Öffnet den Such-Dialog"""
        if not self.extractor:
            self.notify("Keine Datenbank geladen", severity="warning")
            return

        def handle_result(result: Optional[Dict]) -> None:
            if result:
                viewer = self.query_one("#code-viewer", CodeViewer)
                title = f"{result['table_name']}.{result['element_name'] or result['code_type']}"
                viewer.update_code(result['code'], title)
                self.query_one("#tab-content", TabbedContent).active = "tab-scripts"

        self.push_screen(SearchScreen(self.extractor), handle_result)

    def action_refresh(self) -> None:
        """Aktualisiert die Ansicht"""
        self.load_database()

    def action_toggle_sidebar(self) -> None:
        """Blendet die Sidebar ein/aus"""
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display

    def action_tab_fields(self) -> None:
        """Wechselt zum Felder-Tab"""
        self.query_one("#tab-content", TabbedContent).active = "tab-fields"

    def action_tab_scripts(self) -> None:
        """Wechselt zum Scripts-Tab"""
        self.query_one("#tab-content", TabbedContent).active = "tab-scripts"

    def action_tab_deps(self) -> None:
        """Wechselt zum Abhängigkeiten-Tab"""
        self.query_one("#tab-content", TabbedContent).active = "tab-deps"

    def action_help(self) -> None:
        """Zeigt Hilfe an"""
        help_text = """
[bold cyan]Tastenkürzel:[/bold cyan]

[yellow]q[/yellow]  Beenden
[yellow]s[/yellow]  Suchen
[yellow]r[/yellow]  Aktualisieren
[yellow]f[/yellow]  Sidebar ein/aus

[yellow]1[/yellow]  Tab: Felder
[yellow]2[/yellow]  Tab: Scripts
[yellow]3[/yellow]  Tab: Abhängigkeiten

[yellow]↑↓[/yellow] Navigation
[yellow]Enter[/yellow] Auswählen
        """
        self.notify(help_text, title="Hilfe", timeout=10)


# =============================================================================
# Main
# =============================================================================

def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB

    if not Path(db_path).exists():
        print(f"Datenbank nicht gefunden: {db_path}")
        print(f"Bitte zuerst extrahieren: ./ninox_cli.py extract ...")
        sys.exit(1)

    app = NinoxTUI(db_path)
    app.run()


if __name__ == "__main__":
    main()
