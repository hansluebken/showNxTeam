#!/usr/bin/env python3
"""
Ninox Scripts Viewer - Python/Textual Version

Zeigt alle Scripts in einer übersichtlichen Liste mit vollständigem Code.
Unterstützt AND/OR Filter-Logik und Dark/Light Themes.
"""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Input, Label
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.text import Text
from rich.panel import Panel
from rich.table import Table

# =============================================================================
# Datentypen
# =============================================================================

@dataclass
class Script:
    id: int
    database_id: str
    database_name: str
    table_id: str
    table_name: str
    element_id: str
    element_name: str
    code_type: str
    code_category: str
    code: str
    line_count: int


# =============================================================================
# Datenbank
# =============================================================================

def load_scripts(db_path: str) -> list[Script]:
    """Lädt alle Scripts aus der Datenbank."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, database_id, database_name, table_id, table_name,
               element_id, element_name, code_type, code_category, code, line_count
        FROM scripts
        ORDER BY database_name, table_name, element_name, code_type
    """)

    scripts = []
    for row in cursor.fetchall():
        scripts.append(Script(
            id=row[0],
            database_id=row[1],
            database_name=row[2],
            table_id=row[3] or "",
            table_name=row[4] or "",
            element_id=row[5] or "",
            element_name=row[6] or "",
            code_type=row[7],
            code_category=row[8] or "",
            code=row[9],
            line_count=row[10]
        ))

    conn.close()
    return scripts


# =============================================================================
# Filter
# =============================================================================

def filter_scripts(scripts: list[Script], filter_text: str) -> list[Script]:
    """Filtert Scripts mit AND/OR Logik."""
    filter_text = filter_text.strip()
    if not filter_text:
        return scripts

    result = []
    or_groups = filter_text.split(" OR ")

    for script in scripts:
        search_text = " ".join([
            script.database_name,
            script.table_name,
            script.element_name,
            script.code_type,
            script.code_category,
            script.code
        ]).lower()

        for or_group in or_groups:
            or_group = or_group.strip()
            if not or_group:
                continue

            and_terms = or_group.split(" AND ")
            all_match = True

            for term in and_terms:
                term = term.strip().lower()
                if term and term not in search_text:
                    all_match = False
                    break

            if all_match:
                result.append(script)
                break

    return result


# =============================================================================
# Widgets
# =============================================================================

class ScriptRow(Static):
    """Eine Script-Zeile mit Header und Code-Preview."""

    def __init__(self, script: Script, selected: bool = False, col_widths: dict = None):
        super().__init__()
        self.script = script
        self.selected = selected
        self.col_widths = col_widths or {}

    def compose(self) -> ComposeResult:
        yield Static(id="content")

    def on_mount(self):
        self.update_content()

    def update_content(self):
        s = self.script
        w = self.col_widths

        elem = s.element_name or "(Tabelle)"

        # Header-Zeile
        prefix = "▶ " if self.selected else "  "
        header = f"{prefix}{s.database_name:<{w.get('database', 20)}} │ {s.table_name:<{w.get('table', 20)}} │ {elem:<{w.get('element', 20)}} │ {s.code_type:<{w.get('type', 10)}} │ {s.code_category}"

        # Code-Preview mit Syntax-Highlighting
        code_lines = s.code.split("\n")
        max_lines = min(12, len(code_lines))
        preview_code = "\n".join(code_lines[:max_lines])
        if len(code_lines) > max_lines:
            preview_code += f"\n... (+{len(code_lines) - max_lines} Zeilen)"

        syntax = Syntax(preview_code, "javascript", theme="monokai", line_numbers=True)

        border_style = "bright_cyan" if self.selected else "dim"
        header_style = "bold bright_white on dark_blue" if self.selected else "white"

        content = self.query_one("#content", Static)
        content.update(
            Text(header, style=header_style)
        )

        self.border_title = f"{s.code_type}"
        self.styles.border = ("round", border_style)


class ScriptList(ScrollableContainer):
    """Scrollbare Liste aller Scripts."""

    def __init__(self, scripts: list[Script], col_widths: dict):
        super().__init__()
        self.scripts = scripts
        self.col_widths = col_widths
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        for i, script in enumerate(self.scripts):
            yield ScriptRow(script, selected=(i == 0), col_widths=self.col_widths)

    def update_selection(self, new_index: int):
        if not self.scripts:
            return

        old_index = self.selected_index
        self.selected_index = max(0, min(new_index, len(self.scripts) - 1))

        rows = list(self.query(ScriptRow))
        if old_index < len(rows):
            rows[old_index].selected = False
            rows[old_index].styles.border = ("round", "dim")
        if self.selected_index < len(rows):
            rows[self.selected_index].selected = True
            rows[self.selected_index].styles.border = ("round", "bright_cyan")
            rows[self.selected_index].scroll_visible()


class CodeViewer(ScrollableContainer):
    """Vollständige Code-Ansicht mit Syntax-Highlighting."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script

    def compose(self) -> ComposeResult:
        s = self.script

        # Header
        header = f"""═══════════════════════════════════════════════════════════
  Datenbank:  {s.database_name}
  Tabelle:    {s.table_name}
  Element:    {s.element_name or '(Tabelle)'}
  Typ:        {s.code_type} ({s.code_category})
  Zeilen:     {s.line_count}
═══════════════════════════════════════════════════════════"""

        yield Static(Text(header, style="bold bright_cyan"), id="code-header")
        yield Static(Syntax(s.code, "javascript", theme="monokai", line_numbers=True), id="code-content")


# =============================================================================
# Haupt-App
# =============================================================================

class NinoxScriptsApp(App):
    """Ninox Scripts Viewer TUI."""

    CSS = """
    Screen {
        background: $surface;
    }

    #title-bar {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
        text-style: bold;
    }

    #filter-container {
        dock: top;
        height: 3;
        padding: 0 1;
    }

    #filter-input {
        width: 100%;
    }

    #filter-info {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #header-row {
        dock: top;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    #script-list {
        height: 1fr;
    }

    ScriptRow {
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1;
        border: round $primary-darken-3;
    }

    ScriptRow #content {
        height: auto;
    }

    #code-viewer {
        height: 1fr;
        margin: 1;
        padding: 1;
        border: round $primary;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Beenden"),
        Binding("escape", "back", "Zurück"),
        Binding("enter", "select", "Anzeigen"),
        Binding("f", "filter", "Filter"),
        Binding("c", "clear", "Löschen"),
        Binding("up", "up", "Hoch", show=False),
        Binding("down", "down", "Runter", show=False),
        Binding("k", "up", "Hoch", show=False),
        Binding("j", "down", "Runter", show=False),
        Binding("pageup", "page_up", "Seite hoch", show=False),
        Binding("pagedown", "page_down", "Seite runter", show=False),
    ]

    filter_text = reactive("")
    showing_code = reactive(False)
    filtering = reactive(False)

    def __init__(self, scripts: list[Script], theme: str = "dark"):
        super().__init__()
        self.all_scripts = scripts
        self.filtered_scripts = scripts
        self.selected_index = 0
        self.col_widths = self.calculate_widths(scripts)
        self.theme_name = theme

    def calculate_widths(self, scripts: list[Script]) -> dict:
        """Berechnet optimale Spaltenbreiten."""
        w = {"database": 8, "table": 7, "element": 7, "type": 3, "category": 8}

        for s in scripts:
            w["database"] = max(w["database"], len(s.database_name))
            w["table"] = max(w["table"], len(s.table_name))
            elem = s.element_name or "(Tabelle)"
            w["element"] = max(w["element"], len(elem))
            w["type"] = max(w["type"], len(s.code_type))
            w["category"] = max(w["category"], len(s.code_category))

        # Maximalwerte
        w["database"] = min(w["database"], 30)
        w["table"] = min(w["table"], 30)
        w["element"] = min(w["element"], 30)
        w["type"] = min(w["type"], 15)
        w["category"] = min(w["category"], 12)

        return w

    def compose(self) -> ComposeResult:
        total = len(self.all_scripts)
        yield Static(f" Ninox Scripts ({total})", id="title-bar")
        yield Container(
            Input(placeholder="Filter: Begriff AND Begriff OR Begriff...", id="filter-input"),
            id="filter-container"
        )
        yield Static("", id="filter-info")

        # Header
        w = self.col_widths
        header = f"  {'Datenbank':<{w['database']}} │ {'Tabelle':<{w['table']}} │ {'Element':<{w['element']}} │ {'Typ':<{w['type']}} │ Kategorie"
        yield Static(header, id="header-row")

        yield ScrollableContainer(id="script-list")
        yield Static(" ↑↓ Nav │ Enter Code │ f Filter │ c Clear │ q Quit", id="status-bar")

    def on_mount(self):
        self.query_one("#filter-container").display = False
        self.refresh_list()

    def refresh_list(self):
        """Aktualisiert die Script-Liste."""
        container = self.query_one("#script-list", ScrollableContainer)
        container.remove_children()

        for i, script in enumerate(self.filtered_scripts):
            row = ScriptRow(script, selected=(i == self.selected_index), col_widths=self.col_widths)
            container.mount(row)

        # Titel aktualisieren
        total = len(self.all_scripts)
        filtered = len(self.filtered_scripts)
        if filtered != total:
            title = f" Ninox Scripts ({filtered} von {total})"
        else:
            title = f" Ninox Scripts ({total})"
        self.query_one("#title-bar", Static).update(title)

        # Filter-Info
        if self.filter_text:
            self.query_one("#filter-info", Static).update(f"  Filter: {self.filter_text}  │  c = löschen")
        else:
            self.query_one("#filter-info", Static).update("")

    def update_selection(self, new_index: int):
        """Aktualisiert die Auswahl."""
        if not self.filtered_scripts:
            return

        old_index = self.selected_index
        self.selected_index = max(0, min(new_index, len(self.filtered_scripts) - 1))

        rows = list(self.query("#script-list ScriptRow"))
        if old_index < len(rows):
            rows[old_index].selected = False
            rows[old_index].styles.border = ("round", "dim")
        if self.selected_index < len(rows):
            rows[self.selected_index].selected = True
            rows[self.selected_index].styles.border = ("round", "bright_cyan")
            rows[self.selected_index].scroll_visible()

        # Status aktualisieren
        pos = f" {self.selected_index + 1}/{len(self.filtered_scripts)}"
        self.query_one("#status-bar", Static).update(f"{pos} │ ↑↓ Nav │ Enter Code │ f Filter │ c Clear │ q Quit")

    def action_up(self):
        if not self.showing_code and not self.filtering:
            self.update_selection(self.selected_index - 1)

    def action_down(self):
        if not self.showing_code and not self.filtering:
            self.update_selection(self.selected_index + 1)

    def action_page_up(self):
        if not self.showing_code and not self.filtering:
            self.update_selection(self.selected_index - 5)

    def action_page_down(self):
        if not self.showing_code and not self.filtering:
            self.update_selection(self.selected_index + 5)

    def action_filter(self):
        if not self.showing_code:
            self.filtering = True
            self.query_one("#filter-container").display = True
            self.query_one("#filter-input", Input).focus()

    def action_clear(self):
        if not self.showing_code and not self.filtering:
            self.filter_text = ""
            self.filtered_scripts = self.all_scripts
            self.selected_index = 0
            self.col_widths = self.calculate_widths(self.all_scripts)
            self.refresh_list()

    def action_select(self):
        if self.filtering:
            # Filter anwenden
            self.filter_text = self.query_one("#filter-input", Input).value
            self.filtering = False
            self.query_one("#filter-container").display = False

            if self.filter_text:
                self.filtered_scripts = filter_scripts(self.all_scripts, self.filter_text)
            else:
                self.filtered_scripts = self.all_scripts

            self.selected_index = 0
            self.col_widths = self.calculate_widths(self.filtered_scripts)
            self.refresh_list()
        elif not self.showing_code and self.filtered_scripts:
            # Code anzeigen
            self.showing_code = True
            script = self.filtered_scripts[self.selected_index]

            self.query_one("#script-list").display = False
            self.query_one("#header-row").display = False
            self.query_one("#filter-info").display = False

            viewer = CodeViewer(script)
            viewer.id = "code-viewer"
            self.mount(viewer)

            self.query_one("#title-bar", Static).update(f" Code: {script.element_name or script.table_name}")
            self.query_one("#status-bar", Static).update(" ↑↓ Scroll │ Esc/Enter Zurück │ q Beenden")

    def action_back(self):
        if self.filtering:
            self.filtering = False
            self.query_one("#filter-container").display = False
        elif self.showing_code:
            self.showing_code = False
            viewer = self.query_one("#code-viewer", CodeViewer)
            viewer.remove()

            self.query_one("#script-list").display = True
            self.query_one("#header-row").display = True
            self.query_one("#filter-info").display = True

            total = len(self.all_scripts)
            filtered = len(self.filtered_scripts)
            if filtered != total:
                title = f" Ninox Scripts ({filtered} von {total})"
            else:
                title = f" Ninox Scripts ({total})"
            self.query_one("#title-bar", Static).update(title)
            self.query_one("#status-bar", Static).update(" ↑↓ Nav │ Enter Code │ f Filter │ c Clear │ q Quit")

    def on_input_submitted(self, event: Input.Submitted):
        if self.filtering:
            self.action_select()


# =============================================================================
# Main
# =============================================================================

def print_usage():
    print("Ninox Scripts Viewer")
    print("")
    print("Zeigt alle Scripts in einer übersichtlichen Liste mit vollständigem Code.")
    print("")
    print("Verwendung:")
    print("  ninox_scripts.py [optionen] [datenbank.db]")
    print("")
    print("Optionen:")
    print("  --dark, -d   Dunkles Farbschema (Standard)")
    print("  --light, -l  Helles Farbschema")
    print("  --help, -h   Diese Hilfe")
    print("")
    print("Tasten:")
    print("  ↑/k ↓/j      Navigation")
    print("  Enter        Vollständigen Code anzeigen")
    print("  f            Filter eingeben")
    print("  c            Filter löschen")
    print("  PgUp/PgDn    Seitenweise scrollen")
    print("  q            Beenden")
    print("")
    print("Filter:")
    print("  text         Einfache Suche")
    print("  A AND B      Beide müssen vorkommen")
    print("  A OR B       Einer muss vorkommen")


def main():
    db_path = "ninox_schema.db"
    theme = "dark"

    args = sys.argv[1:]
    for arg in args:
        if arg in ("--help", "-h"):
            print_usage()
            sys.exit(0)
        elif arg in ("--dark", "-d"):
            theme = "dark"
        elif arg in ("--light", "-l"):
            theme = "light"
        elif not arg.startswith("-"):
            db_path = arg
        else:
            print(f"Unbekannte Option: {arg}")
            print_usage()
            sys.exit(1)

    if not Path(db_path).exists():
        print(f"Datenbank nicht gefunden: {db_path}")
        print("Bitte zuerst Daten extrahieren.")
        sys.exit(1)

    try:
        scripts = load_scripts(db_path)
    except Exception as e:
        print(f"Fehler beim Laden: {e}")
        sys.exit(1)

    if not scripts:
        print("Keine Scripts gefunden.")
        sys.exit(0)

    app = NinoxScriptsApp(scripts, theme)
    app.run()


if __name__ == "__main__":
    main()
