#!/usr/bin/env python3
"""Zeigt den Inhalt der netzfabrik.db SQLite-Datenbank an."""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "netzfabrik.db"

# ============================================================================
# Integration der Ninox-Module für Code-Formatierung
# ============================================================================

# Importiere Funktionen aus den vorhandenen Modulen
try:
    from ninox_lexer import format_code, get_code_preview
    HAS_LEXER = True
except ImportError:
    HAS_LEXER = False
    def format_code(code, indent_size=4):
        return code
    def get_code_preview(code, max_length=100):
        return code[:max_length] + "..." if len(code) > max_length else code

try:
    from ninox_md_generator import clean_code
    HAS_MD_GENERATOR = True
except ImportError:
    HAS_MD_GENERATOR = False
    def clean_code(code):
        """Fallback: Bereinigt escaped Strings."""
        if not code:
            return ""
        return code.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').strip()

try:
    from ninox_yaml_parser import CODE_TYPE_NAMES
    HAS_YAML_PARSER = True
except ImportError:
    HAS_YAML_PARSER = False
    # Fallback: Eigene Typ-Namen
    CODE_TYPE_NAMES = {
        'afterOpen': 'After Open (DB)',
        'beforeOpen': 'Before Open (DB)',
        'globalCode': 'Global Code',
        'afterCreate': 'After Create',
        'afterUpdate': 'After Update',
        'afterDelete': 'After Delete',
        'beforeDelete': 'Before Delete',
        'fn': 'Formula',
        'constraint': 'Constraint',
        'dchoiceValues': 'Dynamic Choice Values',
        'dchoiceCaption': 'Dynamic Choice Caption',
        'dchoiceColor': 'Dynamic Choice Color',
        'dchoiceIcon': 'Dynamic Choice Icon',
        'referenceFormat': 'Reference Format',
        'visibility': 'Visibility',
        'onClick': 'On Click',
        'onDoubleClick': 'On Double Click',
        'beforeShow': 'Before Show',
        'afterShow': 'After Show',
        'afterHide': 'After Hide',
        'expression': 'Expression',
        'filter': 'Filter',
        'canRead': 'Can Read',
        'canWrite': 'Can Write',
        'canCreate': 'Can Create',
        'canDelete': 'Can Delete',
        'validation': 'Validation',
        'printout': 'Print Layout',
        'color': 'Color Formula',
    }


def get_type_display_name(code_type: str) -> str:
    """Gibt den menschenlesbaren Namen für einen Code-Typ zurück."""
    return CODE_TYPE_NAMES.get(code_type, code_type)


def print_separator(title: str = ""):
    """Gibt eine Trennlinie mit optionalem Titel aus."""
    if title:
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print('=' * 60)
    else:
        print('-' * 60)


def show_databases(cur: sqlite3.Cursor):
    """Zeigt alle Datenbanken."""
    print_separator("DATENBANKEN")
    cur.execute("SELECT id, name, table_count, code_count, extracted_at FROM databases")
    rows = cur.fetchall()
    if not rows:
        print("Keine Datenbanken gefunden.")
        return

    for row in rows:
        print(f"\n  ID: {row[0]}")
        print(f"  Name: {row[1]}")
        print(f"  Tabellen: {row[2]}")
        print(f"  Code-Einträge: {row[3]}")
        print(f"  Extrahiert: {row[4]}")


def show_tables(cur: sqlite3.Cursor):
    """Zeigt alle Tabellen."""
    print_separator("TABELLEN")
    cur.execute("""
        SELECT t.table_id, t.name, t.caption, t.field_count, d.name as db_name
        FROM tables t
        JOIN databases d ON t.database_id = d.id
        ORDER BY d.name, t.name
    """)
    rows = cur.fetchall()
    if not rows:
        print("Keine Tabellen gefunden.")
        return

    current_db = None
    for row in rows:
        if current_db != row[4]:
            current_db = row[4]
            print(f"\n  [{current_db}]")

        caption = f" ({row[2]})" if row[2] and row[2] != row[1] else ""
        print(f"    - {row[1]}{caption} [ID: {row[0]}, Felder: {row[3]}]")


def show_fields(cur: sqlite3.Cursor, limit: int = 50):
    """Zeigt Felder (limitiert)."""
    print_separator(f"FELDER (erste {limit})")
    cur.execute(f"""
        SELECT f.name, f.caption, f.base_type, t.name as table_name, d.name as db_name
        FROM fields f
        JOIN tables t ON f.table_id = t.table_id AND f.database_id = t.database_id
        JOIN databases d ON f.database_id = d.id
        ORDER BY d.name, t.name, f.name
        LIMIT {limit}
    """)
    rows = cur.fetchall()
    if not rows:
        print("Keine Felder gefunden.")
        return

    for row in rows:
        caption = f" ({row[1]})" if row[1] and row[1] != row[0] else ""
        print(f"  {row[4]}.{row[3]}.{row[0]}{caption} [{row[2]}]")


def show_relationships(cur: sqlite3.Cursor):
    """Zeigt Beziehungen zwischen Tabellen."""
    print_separator("BEZIEHUNGEN")
    cur.execute("""
        SELECT source_table_name, target_table_name, relationship_type,
               source_field_name, database_name
        FROM relationships
        ORDER BY database_name, source_table_name
    """)
    rows = cur.fetchall()
    if not rows:
        print("Keine Beziehungen gefunden.")
        return

    for row in rows:
        field_info = f" via '{row[3]}'" if row[3] else ""
        print(f"  {row[0]} -> {row[1]} [{row[2]}]{field_info}")


def show_scripts(cur: sqlite3.Cursor, limit: int = 20):
    """Zeigt Skripte (limitiert)."""
    print_separator(f"SKRIPTE (erste {limit})")
    cur.execute(f"""
        SELECT table_name, element_name, code_type, code_category,
               line_count, substr(code, 1, 150) as code_preview
        FROM scripts
        ORDER BY database_name, table_name
        LIMIT {limit}
    """)
    rows = cur.fetchall()
    if not rows:
        print("Keine Skripte gefunden.")
        return

    for row in rows:
        table = row[0] or "(global)"
        element = row[1] or "-"
        code_type = row[2] or "-"
        type_display = get_type_display_name(code_type)

        # Bereinige und kürze Vorschau
        preview = clean_code(row[5]) if row[5] else ""
        preview = preview.replace('\n', ' ').strip()
        if len(preview) > 80:
            preview = preview[:80] + "..."

        print(f"\n  Tabelle: {table}")
        print(f"  Element: {element}")
        print(f"  Typ: {type_display} ({code_type})")
        print(f"  Zeilen: {row[4]}")
        print(f"  Vorschau: {preview}")


def show_scripts_paginated(cur: sqlite3.Cursor, page_size: int = 10):
    """Zeigt Skripte mit paginierter Ausgabe."""
    # Gesamtanzahl ermitteln
    cur.execute("SELECT COUNT(*) FROM scripts")
    total = cur.fetchone()[0]

    if total == 0:
        print("Keine Skripte gefunden.")
        return

    total_pages = (total + page_size - 1) // page_size
    current_page = 1

    while True:
        offset = (current_page - 1) * page_size

        cur.execute("""
            SELECT database_name, table_name, element_name, code_type, code
            FROM scripts
            ORDER BY database_name, table_name, element_name
            LIMIT ? OFFSET ?
        """, (page_size, offset))
        rows = cur.fetchall()

        # Bildschirm "leeren" mit Abstand
        print("\n" * 2)
        print_separator(f"SKRIPTE - Seite {current_page}/{total_pages} ({total} gesamt)")

        for i, row in enumerate(rows, start=offset + 1):
            db_name = row[0] or "(unbekannt)"
            table_name = row[1] or "(global)"
            field_name = row[2] or "-"
            script_type = row[3] or "-"
            code = row[4] or ""

            # 1. Escaped Strings bereinigen (\\n → \n, etc.)
            code = clean_code(code)

            # 2. Code formatieren mit Einrückung (aus ninox_lexer)
            if HAS_LEXER:
                code = format_code(code)

            # 3. Typ-Namen menschenlesbar machen
            type_display = get_type_display_name(script_type)

            # Code-Vorschau (erste 8 Zeilen oder 500 Zeichen)
            code_lines = code.split('\n')
            if len(code_lines) > 8:
                code_preview = '\n'.join(code_lines[:8]) + f"\n    ... ({len(code_lines) - 8} weitere Zeilen)"
            elif len(code) > 500:
                code_preview = code[:500] + "..."
            else:
                code_preview = code

            # Code einrücken für bessere Lesbarkeit
            code_indented = '\n'.join('    ' + line for line in code_preview.split('\n'))

            print(f"\n  [{i}] ─────────────────────────────────────────")
            print(f"  Datenbank:  {db_name}")
            print(f"  Tabelle:    {table_name}")
            print(f"  Feldname:   {field_name}")
            print(f"  Scripttyp:  {type_display} ({script_type})")
            print(f"  Script:")
            print(code_indented)

        # Navigation
        print(f"\n{'─' * 60}")
        print(f"  Seite {current_page}/{total_pages}")
        nav_options = []
        if current_page > 1:
            nav_options.append("[p] Zurück")
        if current_page < total_pages:
            nav_options.append("[n] Weiter")
        nav_options.append("[g] Gehe zu Seite")
        nav_options.append("[q] Beenden")
        print(f"  {' | '.join(nav_options)}")

        try:
            choice = input("\n  Eingabe: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

        if choice == 'q' or choice == '':
            break
        elif choice == 'n' and current_page < total_pages:
            current_page += 1
        elif choice == 'p' and current_page > 1:
            current_page -= 1
        elif choice == 'g':
            try:
                page_input = input(f"  Seitennummer (1-{total_pages}): ").strip()
                page_num = int(page_input)
                if 1 <= page_num <= total_pages:
                    current_page = page_num
                else:
                    print(f"  Ungültige Seite. Bitte 1-{total_pages} eingeben.")
            except ValueError:
                print("  Ungültige Eingabe.")
        elif choice.isdigit():
            page_num = int(choice)
            if 1 <= page_num <= total_pages:
                current_page = page_num


def show_statistics(cur: sqlite3.Cursor):
    """Zeigt Statistiken."""
    print_separator("STATISTIKEN")

    stats = [
        ("Datenbanken", "SELECT COUNT(*) FROM databases"),
        ("Tabellen", "SELECT COUNT(*) FROM tables"),
        ("Felder", "SELECT COUNT(*) FROM fields"),
        ("Beziehungen", "SELECT COUNT(*) FROM relationships"),
        ("Skripte", "SELECT COUNT(*) FROM scripts"),
        ("Gesamt-Codezeilen", "SELECT COALESCE(SUM(line_count), 0) FROM scripts"),
    ]

    for name, query in stats:
        cur.execute(query)
        count = cur.fetchone()[0]
        print(f"  {name}: {count}")


def print_usage():
    """Zeigt Hilfe an."""
    print("""
Verwendung: python3 show_db.py [BEFEHL] [OPTIONEN]

Befehle:
  (ohne)              Zeigt Übersicht aller Daten
  scripts             Paginierte Skript-Ansicht (interaktiv)
  scripts --size N    Anzahl Skripte pro Seite (Standard: 10)

Beispiele:
  python3 show_db.py                 # Übersicht
  python3 show_db.py scripts         # Skripte durchblättern
  python3 show_db.py scripts --size 5
""")


def main():
    if not DB_PATH.exists():
        print(f"Fehler: Datenbank nicht gefunden: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # CLI-Argumente parsen
    args = sys.argv[1:]

    if len(args) == 0:
        # Standard: Übersicht
        print(f"\nDatenbank: {DB_PATH}")
        show_statistics(cur)
        show_databases(cur)
        show_tables(cur)
        show_relationships(cur)
        show_scripts(cur)
        show_fields(cur)
        print("\n")

    elif args[0] == 'scripts':
        # Paginierte Skript-Ansicht
        page_size = 10
        if '--size' in args:
            try:
                size_idx = args.index('--size')
                page_size = int(args[size_idx + 1])
            except (IndexError, ValueError):
                print("Fehler: --size benötigt eine Zahl")
                sys.exit(1)

        print(f"\nDatenbank: {DB_PATH}")
        show_scripts_paginated(cur, page_size)

    elif args[0] in ['-h', '--help', 'help']:
        print_usage()

    else:
        print(f"Unbekannter Befehl: {args[0]}")
        print_usage()
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
