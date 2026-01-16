#!/usr/bin/env python3
"""
Ninox Database Viewer - Interaktives CLI-Tool zur Anzeige der extrahierten Daten.
"""

import sqlite3
import sys
import os
import subprocess
from pathlib import Path

# Pfade
SCRIPT_DIR = Path(__file__).parent
DEFAULT_DB = SCRIPT_DIR / "ninoxstructur.db"
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
EXTRACTOR = SCRIPT_DIR / "ninox_api_extractor.py"

# ANSI Farben
class C:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    DARKBLUE = '\033[34m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BG_BLUE = '\033[44m'
    BG_GREEN = '\033[42m'
    BG_MAGENTA = '\033[45m'
    # Menü-Optionen Farbe
    KEY = '\033[34m\033[1m'  # Dunkelblau + Bold

# Code-Typ Namen
CODE_TYPE_NAMES = {
    'globalCode': 'Global Code',
    'afterCreate': 'After Create',
    'afterUpdate': 'After Update',
    'beforeDelete': 'Before Delete',
    'fn': 'Formula',
    'constraint': 'Constraint',
    'dchoiceValues': 'Dynamic Choice',
    'onClick': 'On Click',
    'beforeShow': 'Before Show',
    'afterHide': 'After Hide',
    'canRead': 'Can Read',
    'canWrite': 'Can Write',
    'canCreate': 'Can Create',
    'canDelete': 'Can Delete',
    'validation': 'Validation',
}


def clear():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_type_name(code_type: str) -> str:
    return CODE_TYPE_NAMES.get(code_type, code_type)


def clean_code(code: str) -> str:
    if not code:
        return ""
    return code.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').strip()


def safe_input(prompt: str, valid_options: list = None, allow_empty: bool = True) -> str:
    """Sichere Eingabe mit Validierung."""
    while True:
        try:
            value = input(prompt).strip()
            value_lower = value.lower()
            if allow_empty and value == '':
                return ''
            if valid_options is None:
                return value
            if value_lower in valid_options:
                return value_lower
            print(f"  {C.RED}Ungültig. Erlaubt: {', '.join(valid_options)}{C.RESET}")
        except (KeyboardInterrupt, EOFError):
            return 'q'


def load_config() -> dict:
    """Lädt config.yaml und gibt Environments zurück."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        if config is None:
            return {}
        return config.get('environments', {})
    except:
        return {}


def save_config(environments: dict):
    """Speichert Environments in config.yaml."""
    try:
        import yaml
        config = {'environments': environments}
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return True
    except Exception as e:
        print(f"  {C.RED}Fehler beim Speichern: {e}{C.RESET}")
        return False


def create_config_wizard() -> dict:
    """Interaktive Eingabemaske zur Konfigurationserstellung."""
    clear()
    print(f"""
{C.BG_MAGENTA}{C.WHITE}{C.BOLD}  KONFIGURATION ERSTELLEN                                                  {C.RESET}

  {C.BOLD}NINOX API ZUGANGSDATEN{C.RESET}
  ─────────────────────────────────────────────────────
  Diese Daten findest Du in Ninox unter:
  {C.CYAN}Einstellungen > Team > API-Key{C.RESET}

  {C.DIM}Die Workspace-ID findest Du in der URL wenn Du
  im Team-Bereich bist (z.B. https://domain/teams/XXXX){C.RESET}
""")
    environments = {}

    while True:
        print(f"\n  {C.BOLD}NEUES ENVIRONMENT ANLEGEN{C.RESET}")
        print(f"  {C.DIM}(Leere Eingabe bei Name = Abbrechen){C.RESET}\n")

        # Environment Name
        env_name = input(f"  {C.YELLOW}Environment-Name{C.RESET} (z.B. production, dev): ").strip()
        if not env_name:
            if environments:
                break
            print(f"  {C.RED}Mindestens ein Environment wird benötigt!{C.RESET}")
            continue

        # Domain
        while True:
            domain = input(f"  {C.YELLOW}Domain{C.RESET} (z.B. https://firma.ninoxdb.de): ").strip()
            if domain:
                if not domain.startswith('http'):
                    domain = 'https://' + domain
                break
            print(f"  {C.RED}Domain ist erforderlich!{C.RESET}")

        # Workspace ID
        while True:
            workspace_id = input(f"  {C.YELLOW}Workspace-ID{C.RESET}: ").strip()
            if workspace_id:
                break
            print(f"  {C.RED}Workspace-ID ist erforderlich!{C.RESET}")

        # Team Name (optional)
        team_name = input(f"  {C.YELLOW}Team-Name{C.RESET} (optional, für Anzeige): ").strip()
        if not team_name:
            team_name = env_name.capitalize()

        # API Key
        while True:
            api_key = input(f"  {C.YELLOW}API-Key{C.RESET}: ").strip()
            if api_key:
                break
            print(f"  {C.RED}API-Key ist erforderlich!{C.RESET}")

        environments[env_name] = {
            'domain': domain,
            'workspaceId': workspace_id,
            'teamName': team_name,
            'apiKey': api_key
        }

        print(f"\n  {C.GREEN}✓{C.RESET} Environment '{C.BOLD}{env_name}{C.RESET}' hinzugefügt")

        # Weitere hinzufügen?
        more = safe_input(f"\n  Weiteres Environment hinzufügen? ({C.KEY}j{C.RESET}/{C.KEY}n{C.RESET}): ", ['j', 'n', 'ja', 'nein'])
        if more not in ['j', 'ja']:
            break

    return environments


def config_menu():
    """Menü zur Konfigurationsverwaltung."""
    clear()
    existing = load_config()

    print(f"""
{C.BG_MAGENTA}{C.WHITE}{C.BOLD}  KONFIGURATION                                                            {C.RESET}
""")

    if existing:
        print(f"  {C.BOLD}VORHANDENE ENVIRONMENTS{C.RESET}")
        print(f"  ─────────────────────────────────────────────────────")
        for name, env in existing.items():
            print(f"  {C.CYAN}■{C.RESET} {C.BOLD}{name}{C.RESET}")
            print(f"    {C.DIM}Domain: {env.get('domain', '-')}{C.RESET}")
            print(f"    {C.DIM}Team: {env.get('teamName', '-')}{C.RESET}")
            print()

        print(f"  {C.KEY}a{C.RESET}  Environment hinzufügen")
        print(f"  {C.KEY}n{C.RESET}  Neu erstellen (überschreibt alles)")
        print(f"  {C.KEY}q{C.RESET}  Zurück")

        choice = safe_input(f"\n  {C.BOLD}>{C.RESET} ", ['a', 'n', 'q'])

        if choice == 'a':
            # Einzelnes Environment hinzufügen
            new_envs = create_config_wizard()
            if new_envs:
                existing.update(new_envs)
                if save_config(existing):
                    print(f"\n  {C.GREEN}✓ Konfiguration gespeichert!{C.RESET}")
                input(f"\n  {C.DIM}[Enter] Weiter{C.RESET}")
            return existing
        elif choice == 'n':
            confirm = safe_input(f"  {C.RED}Wirklich alle Environments löschen?{C.RESET} (j/n): ", ['j', 'n'])
            if confirm != 'j':
                return existing
            existing = {}
        else:
            return existing

    # Neu erstellen
    new_envs = create_config_wizard()
    if new_envs:
        if save_config(new_envs):
            print(f"\n  {C.GREEN}✓ Konfiguration gespeichert in config.yaml!{C.RESET}")
        input(f"\n  {C.DIM}[Enter] Weiter{C.RESET}")
        return new_envs

    return existing


def parse_search_query(query: str) -> tuple:
    """
    Parst Suchquery mit AND/OR Unterstützung.

    Beispiele:
        "create AND update"     -> (['create', 'update'], 'AND')
        "email OR telefon"      -> (['email', 'telefon'], 'OR')
        "create"                -> (['create'], 'AND')

    Returns:
        (terms, operator)
    """
    query_upper = query.upper()

    if ' AND ' in query_upper:
        parts = query.split(' AND ') if ' AND ' in query else query.split(' and ')
        # Case-insensitive split
        import re
        parts = re.split(r'\s+AND\s+', query, flags=re.IGNORECASE)
        return ([p.strip() for p in parts if p.strip()], 'AND')
    elif ' OR ' in query_upper:
        import re
        parts = re.split(r'\s+OR\s+', query, flags=re.IGNORECASE)
        return ([p.strip() for p in parts if p.strip()], 'OR')
    else:
        return ([query.strip()], 'AND')


class NinoxViewer:
    """Interaktiver Viewer für Ninox-Datenbank."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self.cur = None
        self.search_history = []
        self.environments = load_config()
        self._connect()

    def _connect(self):
        """Verbindet zur Datenbank."""
        if self.db_path.exists():
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cur = self.conn.cursor()
        else:
            self.conn = None
            self.cur = None

    def _reconnect(self):
        """Reconnect nach Extraktion."""
        if self.conn:
            self.conn.close()
        self._connect()

    def close(self):
        if self.conn:
            self.conn.close()

    def get_stats(self) -> dict:
        stats = {'databases': 0, 'tables': 0, 'fields': 0, 'scripts': 0, 'dependencies': 0, 'lines': 0}
        if not self.cur:
            return stats
        queries = {
            'databases': "SELECT COUNT(*) FROM databases",
            'tables': "SELECT COUNT(*) FROM tables",
            'fields': "SELECT COUNT(*) FROM fields",
            'scripts': "SELECT COUNT(*) FROM scripts",
            'dependencies': "SELECT COUNT(*) FROM script_dependencies",
            'lines': "SELECT COALESCE(SUM(line_count), 0) FROM scripts",
        }
        for key, query in queries.items():
            try:
                self.cur.execute(query)
                stats[key] = self.cur.fetchone()[0]
            except:
                stats[key] = 0
        return stats

    def run(self):
        """Hauptschleife."""
        while True:
            action = self.show_main_menu()
            if action == 'q':
                break

    def show_main_menu(self):
        """Zeigt Hauptmenü."""
        clear()
        stats = self.get_stats()
        has_data = stats['scripts'] > 0
        has_config = len(self.environments) > 0

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  NINOX DATABASE VIEWER                                                    {C.RESET}

  {C.DIM}Datenbank:{C.RESET} {C.CYAN}{self.db_path.name}{C.RESET}  {C.DIM}({'existiert' if self.db_path.exists() else 'nicht vorhanden'}){C.RESET}
""")
        if has_data:
            print(f"""  {C.BOLD}STATISTIK{C.RESET}
  ─────────────────────────────────────────────────────
  Datenbanken  {C.GREEN}{stats['databases']:>6}{C.RESET}     Scripts      {C.GREEN}{stats['scripts']:>6}{C.RESET}
  Tabellen     {C.GREEN}{stats['tables']:>6}{C.RESET}     Abhängigkeiten {C.GREEN}{stats['dependencies']:>4}{C.RESET}
  Felder       {C.GREEN}{stats['fields']:>6}{C.RESET}     Code-Zeilen  {C.GREEN}{stats['lines']:>6}{C.RESET}
""")
        print(f"""  {C.BOLD}SUCHE & ANZEIGE{C.RESET}
  ─────────────────────────────────────────────────────""")
        if has_data:
            print(f"""  {C.KEY}s{C.RESET}  Suche (AND/OR)    {C.KEY}4{C.RESET}  Tabellen
  {C.KEY}1{C.RESET}  Scripts nach Typ   {C.KEY}5{C.RESET}  Abhängigkeiten
  {C.KEY}2{C.RESET}  Alle Scripts       {C.KEY}6{C.RESET}  Dependency-Matrix
  {C.KEY}3{C.RESET}  Datenbanken""")
        else:
            print(f"  {C.DIM}Keine Daten vorhanden. Bitte zuerst Daten abrufen.{C.RESET}")

        print(f"""
  {C.BOLD}DATEN ABRUFEN{C.RESET}
  ─────────────────────────────────────────────────────""")
        if has_config:
            print(f"  {C.KEY}r{C.RESET}  Daten aus Ninox abrufen (Teams auswählen)")
            print(f"  {C.KEY}c{C.RESET}  Konfiguration bearbeiten")
        else:
            print(f"  {C.KEY}c{C.RESET}  Konfiguration erstellen")

        print(f"""
  {C.KEY}q{C.RESET}  Beenden
  ─────────────────────────────────────────────────────
""")
        valid = ['q', 'c']
        if has_data:
            valid.extend(['s', '1', '2', '3', '4', '5', '6'])
        if has_config:
            valid.append('r')

        choice = safe_input(f"  {C.BOLD}>{C.RESET} ", valid)

        if choice == 'q':
            return 'q'
        elif choice == 's' and has_data:
            self.search_menu()
        elif choice == '1' and has_data:
            self.scripts_by_type()
        elif choice == '2' and has_data:
            self.browse_scripts()
        elif choice == '3' and has_data:
            self.show_databases()
        elif choice == '4' and has_data:
            self.show_tables()
        elif choice == '5' and has_data:
            self.show_dependencies()
        elif choice == '6' and has_data:
            self.show_dependency_matrix()
        elif choice == 'r' and has_config:
            self.extract_menu()
        elif choice == 'c':
            self.environments = config_menu()

        return None

    def extract_menu(self):
        """Menü für Datenextraktion."""
        clear()
        envs = list(self.environments.keys())

        print(f"""
{C.BG_MAGENTA}{C.WHITE}{C.BOLD}  DATEN AUS NINOX ABRUFEN                                                  {C.RESET}

  {C.BOLD}VERFÜGBARE TEAMS{C.RESET}
  ─────────────────────────────────────────────────────
""")
        for i, env_name in enumerate(envs, 1):
            env = self.environments[env_name]
            team_name = env.get('teamName', env.get('workspaceId', 'Unbekannt'))
            domain = env.get('domain', '')
            print(f"  {C.KEY}{i}{C.RESET}  {C.BOLD}{env_name}{C.RESET}")
            print(f"     {C.CYAN}{team_name}{C.RESET}")
            print(f"     {C.DIM}{domain}{C.RESET}")
            print()

        print(f"  {C.KEY}a{C.RESET}  Alle Teams abrufen")
        print(f"  {C.KEY}q{C.RESET}  Zurück")
        print()

        valid = ['q', 'a'] + [str(i) for i in range(1, len(envs) + 1)]
        choice = safe_input(f"  {C.BOLD}Auswahl:{C.RESET} ", valid)

        if choice == 'q' or choice == '':
            return

        selected_envs = []
        if choice == 'a':
            selected_envs = envs
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(envs):
                selected_envs = [envs[idx]]

        if selected_envs:
            self.run_extraction(selected_envs)

    def run_extraction(self, env_names: list):
        """Führt Extraktion für ausgewählte Environments aus."""
        # Datenbankverbindung schließen vor Extraktion
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cur = None

        clear()
        print(f"""
{C.BG_MAGENTA}{C.WHITE}{C.BOLD}  EXTRAKTION LÄUFT...                                                      {C.RESET}
""")
        for env_name in env_names:
            print(f"  {C.YELLOW}►{C.RESET} Extrahiere {C.BOLD}{env_name}{C.RESET}...")

            cmd = [
                sys.executable,
                str(EXTRACTOR),
                'extract',
                '--config', str(CONFIG_FILE),
                '--env', env_name,
                '--db', str(self.db_path)
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(SCRIPT_DIR)
                )

                if result.returncode == 0:
                    print(f"  {C.GREEN}✓{C.RESET} {env_name} erfolgreich")
                    # Zeige Statistiken aus Output
                    for line in result.stdout.split('\n'):
                        if 'databases:' in line or 'scripts:' in line:
                            print(f"    {C.DIM}{line.strip()}{C.RESET}")
                else:
                    print(f"  {C.RED}✗{C.RESET} {env_name} fehlgeschlagen")
                    # Zeige Fehler aus stderr oder stdout
                    error_output = result.stderr or result.stdout
                    if error_output:
                        for line in error_output.strip().split('\n')[-10:]:
                            print(f"    {C.RED}{line}{C.RESET}")

            except Exception as e:
                print(f"  {C.RED}✗{C.RESET} Fehler: {e}")

            print()

        # Reconnect zur aktualisierten DB
        self._reconnect()

        print(f"  {C.GREEN}Extraktion abgeschlossen.{C.RESET}")
        input(f"\n  {C.DIM}[Enter] Zurück zum Menü{C.RESET}")

    def search_menu(self):
        """Suchmenü mit AND/OR Unterstützung."""
        clear()
        print(f"""
{C.BG_GREEN}{C.WHITE}{C.BOLD}  SCRIPT-SUCHE                                                             {C.RESET}

  {C.BOLD}SYNTAX{C.RESET}
  ─────────────────────────────────────────────────────
  {C.CYAN}begriff{C.RESET}              Einfache Suche
  {C.CYAN}a AND b{C.RESET}              Beide Begriffe müssen vorkommen
  {C.CYAN}a OR b{C.RESET}               Einer der Begriffe muss vorkommen
  {C.CYAN}tabelle:begriff{C.RESET}      Filtert nach Tabelle
  {C.CYAN}typ:begriff{C.RESET}          Filtert nach Script-Typ

  {C.DIM}Beispiele: "create AND update", "email OR telefon",
             "Kontakte:email", "afterUpdate:http"{C.RESET}
""")
        if self.search_history:
            print(f"  {C.BOLD}LETZTE SUCHEN{C.RESET}")
            print("  ─────────────────────────────────────────────────────")
            for i, h in enumerate(self.search_history[-5:], 1):
                print(f"  {C.DIM}{i}{C.RESET}  {h}")
            print()

        query = input(f"  {C.BOLD}Suche:{C.RESET} ").strip()

        if not query:
            return

        # History-Shortcut
        if query.isdigit() and self.search_history:
            idx = int(query) - 1
            if 0 <= idx < len(self.search_history[-5:]):
                query = self.search_history[-5:][idx]

        if query and query not in self.search_history:
            self.search_history.append(query)

        self.execute_search(query)

    def execute_search(self, query: str):
        """Führt Suche mit AND/OR aus."""
        table_filter = None
        type_filter = None
        search_query = query

        # Prüfe auf Tabellen/Typ-Filter (ohne AND/OR)
        if ':' in query and ' AND ' not in query.upper() and ' OR ' not in query.upper():
            parts = query.split(':', 1)
            prefix = parts[0].lower()
            if prefix in ['tabelle', 'table', 't']:
                table_filter = parts[1]
                search_query = None
            elif prefix in ['typ', 'type']:
                type_filter = parts[1]
                search_query = None
            else:
                table_filter = parts[0]
                search_query = parts[1] if parts[1] else None

        # Parse AND/OR
        terms, operator = parse_search_query(search_query) if search_query else ([], 'AND')

        # SQL bauen
        sql = """
            SELECT s.id, s.database_name, s.table_name, s.element_name,
                   s.code_type, s.code, s.line_count
            FROM scripts s WHERE 1=1
        """
        params = []

        # Suchbegriffe mit AND/OR
        if terms:
            if operator == 'AND':
                # Alle Begriffe müssen vorkommen
                for term in terms:
                    sql += " AND (s.code LIKE ? OR s.element_name LIKE ? OR s.table_name LIKE ?)"
                    params.extend([f'%{term}%'] * 3)
            else:  # OR
                # Mindestens ein Begriff muss vorkommen
                or_conditions = []
                for term in terms:
                    or_conditions.append("(s.code LIKE ? OR s.element_name LIKE ? OR s.table_name LIKE ?)")
                    params.extend([f'%{term}%'] * 3)
                sql += f" AND ({' OR '.join(or_conditions)})"

        if table_filter:
            sql += " AND s.table_name LIKE ?"
            params.append(f'%{table_filter}%')

        if type_filter:
            sql += " AND s.code_type LIKE ?"
            params.append(f'%{type_filter}%')

        sql += " ORDER BY s.database_name, s.table_name LIMIT 100"

        self.cur.execute(sql, params)
        results = list(self.cur.fetchall())

        # Titel für Anzeige
        if terms and len(terms) > 1:
            title = f" {operator} ".join(terms)
        else:
            title = query

        self.show_results(results, title)

    def show_results(self, results: list, title: str):
        """Zeigt Suchergebnisse mit Paginierung."""
        if not results:
            clear()
            print(f"\n  {C.YELLOW}Keine Ergebnisse für '{title}'{C.RESET}")
            input(f"\n  {C.DIM}[Enter] Zurück{C.RESET}")
            return

        page = 0
        page_size = 5
        total_pages = (len(results) + page_size - 1) // page_size

        while True:
            clear()
            start = page * page_size
            end = min(start + page_size, len(results))

            print(f"""
{C.BG_GREEN}{C.WHITE}{C.BOLD}  ERGEBNISSE: {title[:45]}  ({len(results)} Treffer)                    {C.RESET}
""")
            for i, row in enumerate(results[start:end], start=start+1):
                db = row['database_name'] or ''
                tbl = row['table_name'] or '(global)'
                elem = row['element_name'] or '-'
                typ = get_type_name(row['code_type'])

                code = clean_code(row['code'])
                lines = code.split('\n')[:4]
                preview = '\n'.join(f"      {C.DIM}│{C.RESET} {l[:70]}" for l in lines)
                if len(code.split('\n')) > 4:
                    preview += f"\n      {C.DIM}│ ... +{len(code.split(chr(10)))-4} Zeilen{C.RESET}"

                print(f"  {C.KEY}[{i}]{C.RESET} {C.CYAN}{tbl}{C.RESET} › {elem}")
                print(f"      {C.DIM}{db} | {typ} | {row['line_count']} Zeilen{C.RESET}")
                print(preview)
                print()

            # Navigation
            print(f"  {C.DIM}────────────────────────────────────────────────────{C.RESET}")
            nav = [f"Seite {C.BOLD}{page+1}/{total_pages}{C.RESET}"]
            if page > 0:
                nav.append(f"{C.KEY}p{C.RESET}=Zurück")
            if page < total_pages - 1:
                nav.append(f"{C.KEY}n{C.RESET}=Weiter")
            nav.append(f"{C.KEY}Nr{C.RESET}=Details")
            nav.append(f"{C.KEY}s{C.RESET}=Suche")
            nav.append(f"{C.KEY}q{C.RESET}=Menü")
            print(f"  {' | '.join(nav)}")

            valid = ['q', 's', 'n', 'p'] + [str(i) for i in range(1, len(results)+1)]
            choice = safe_input(f"\n  {C.BOLD}>{C.RESET} ", valid)

            if choice == 'q' or choice == '':
                break
            elif choice == 'n' and page < total_pages - 1:
                page += 1
            elif choice == 'p' and page > 0:
                page -= 1
            elif choice == 's':
                self.search_menu()
                break
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    self.show_script_detail(results[idx])

    def show_script_detail(self, script):
        """Zeigt Script-Details."""
        clear()
        code = clean_code(script['code'])

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  SCRIPT DETAILS                                                           {C.RESET}

  {C.BOLD}LOCATION{C.RESET}
  {C.CYAN}{script['database_name']}{C.RESET} › {C.CYAN}{script['table_name'] or '(global)'}{C.RESET} › {script['element_name'] or '-'}

  {C.BOLD}TYP{C.RESET}      {get_type_name(script['code_type'])} ({script['code_type']})
  {C.BOLD}ZEILEN{C.RESET}   {script['line_count']}

  {C.BOLD}CODE{C.RESET}
  {C.DIM}{'─' * 60}{C.RESET}
""")
        for i, line in enumerate(code.split('\n'), 1):
            print(f"  {C.DIM}{i:4}│{C.RESET} {line}")

        print(f"  {C.DIM}{'─' * 60}{C.RESET}")
        input(f"\n  {C.DIM}[Enter] Zurück{C.RESET}")

    def scripts_by_type(self):
        """Scripts nach Typ."""
        clear()
        self.cur.execute("""
            SELECT code_type, COUNT(*) as cnt FROM scripts
            GROUP BY code_type ORDER BY cnt DESC
        """)
        types = list(self.cur.fetchall())

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  SCRIPTS NACH TYP                                                         {C.RESET}
""")
        for i, row in enumerate(types, 1):
            name = get_type_name(row['code_type'])
            cnt = row['cnt']
            bar = '█' * min(cnt // 10, 30)
            print(f"  {C.KEY}{i:2}{C.RESET}  {name:<25} {C.GREEN}{cnt:>5}{C.RESET}  {C.DIM}{bar}{C.RESET}")

        print(f"\n  {C.DIM}Nummer eingeben oder [q] für Zurück{C.RESET}")

        valid = ['q'] + [str(i) for i in range(1, len(types)+1)]
        choice = safe_input(f"\n  {C.BOLD}>{C.RESET} ", valid)

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(types):
                self.cur.execute("""
                    SELECT id, database_name, table_name, element_name,
                           code_type, code, line_count
                    FROM scripts WHERE code_type = ?
                    ORDER BY database_name, table_name LIMIT 100
                """, (types[idx]['code_type'],))
                self.show_results(list(self.cur.fetchall()), get_type_name(types[idx]['code_type']))

    def browse_scripts(self):
        """Alle Scripts durchblättern."""
        self.cur.execute("""
            SELECT id, database_name, table_name, element_name,
                   code_type, code, line_count
            FROM scripts ORDER BY database_name, table_name LIMIT 100
        """)
        self.show_results(list(self.cur.fetchall()), "Alle Scripts")

    def show_databases(self):
        """Zeigt Datenbanken."""
        clear()
        self.cur.execute("SELECT id, name, table_count, code_count FROM databases ORDER BY name")
        rows = self.cur.fetchall()

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  DATENBANKEN                                                              {C.RESET}
""")
        for row in rows:
            print(f"  {C.CYAN}■{C.RESET} {C.BOLD}{row['name']}{C.RESET}")
            print(f"    {C.DIM}ID: {row['id']}{C.RESET}")
            print(f"    Tabellen: {C.GREEN}{row['table_count']}{C.RESET}  Scripts: {C.GREEN}{row['code_count']}{C.RESET}")
            print()

        input(f"  {C.DIM}[Enter] Zurück{C.RESET}")

    def show_tables(self):
        """Zeigt Tabellen."""
        clear()
        self.cur.execute("""
            SELECT t.name, t.caption, t.field_count, d.name as db_name
            FROM tables t JOIN databases d ON t.database_id = d.id
            ORDER BY d.name, t.name
        """)
        rows = self.cur.fetchall()

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  TABELLEN                                                                 {C.RESET}
""")
        current_db = None
        for row in rows:
            if current_db != row['db_name']:
                current_db = row['db_name']
                print(f"\n  {C.CYAN}{C.BOLD}[{current_db}]{C.RESET}")

            caption = f" {C.DIM}({row['caption']}){C.RESET}" if row['caption'] and row['caption'] != row['name'] else ""
            print(f"    ├─ {row['name']}{caption} {C.DIM}[{row['field_count']} Felder]{C.RESET}")

        input(f"\n  {C.DIM}[Enter] Zurück{C.RESET}")

    def show_dependencies(self):
        """Zeigt Abhängigkeiten."""
        clear()
        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  CROSS-DATABASE ABHÄNGIGKEITEN                                            {C.RESET}
""")
        db_filter = input(f"  {C.BOLD}Filter (leer=alle):{C.RESET} ").strip()

        sql = """
            SELECT d.source_database_name, d.target_database_name,
                   d.reference_type, s.table_name, s.element_name
            FROM script_dependencies d
            JOIN scripts s ON d.script_id = s.id
        """
        params = []
        if db_filter:
            sql += " WHERE d.source_database_name LIKE ? OR d.target_database_name LIKE ?"
            params = [f'%{db_filter}%', f'%{db_filter}%']
        sql += " ORDER BY d.source_database_name LIMIT 30"

        self.cur.execute(sql, params)
        rows = self.cur.fetchall()

        clear()
        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  ABHÄNGIGKEITEN ({len(rows)} Einträge)                                     {C.RESET}
""")
        if not rows:
            print(f"  {C.YELLOW}Keine Abhängigkeiten gefunden.{C.RESET}")
        else:
            for row in rows:
                print(f"  {C.CYAN}{row['source_database_name']}{C.RESET} {C.YELLOW}──►{C.RESET} {C.GREEN}{row['target_database_name']}{C.RESET}")
                print(f"    {C.DIM}{row['reference_type']} | {row['table_name'] or '(global)'} > {row['element_name'] or '-'}{C.RESET}")
                print()

        input(f"  {C.DIM}[Enter] Zurück{C.RESET}")

    def show_dependency_matrix(self):
        """Zeigt Dependency-Matrix."""
        clear()
        self.cur.execute("""
            SELECT source_database_name, target_database_name,
                   reference_type, COUNT(*) as cnt
            FROM script_dependencies
            GROUP BY source_database_name, target_database_name, reference_type
            ORDER BY cnt DESC
        """)
        rows = self.cur.fetchall()

        print(f"""
{C.BG_BLUE}{C.WHITE}{C.BOLD}  DEPENDENCY-MATRIX                                                        {C.RESET}

  {C.BOLD}{'VON':<28} {'NACH':<28} {'TYP':<14} {'#':>4}{C.RESET}
  {C.DIM}{'─' * 78}{C.RESET}
""")
        if not rows:
            print(f"  {C.YELLOW}Keine Abhängigkeiten gefunden.{C.RESET}")
        else:
            for row in rows:
                src = row['source_database_name'][:26]
                tgt = row['target_database_name'][:26]
                typ = row['reference_type'][:12]
                print(f"  {C.CYAN}{src:<28}{C.RESET} {C.GREEN}{tgt:<28}{C.RESET} {C.DIM}{typ:<14}{C.RESET} {C.YELLOW}{row['cnt']:>4}{C.RESET}")

        input(f"\n  {C.DIM}[Enter] Zurück{C.RESET}")


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB

    viewer = NinoxViewer(db_path)
    try:
        viewer.run()
    except KeyboardInterrupt:
        pass
    finally:
        viewer.close()
        print(f"\n{C.DIM}Auf Wiedersehen!{C.RESET}\n")


if __name__ == "__main__":
    main()
