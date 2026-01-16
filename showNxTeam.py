#!/usr/bin/env python3
"""
Ninox Database Viewer - dBASE-Style Menüführung
"""

import sqlite3
import sys
import os
import subprocess
import time
from pathlib import Path

# Pfade
SCRIPT_DIR = Path(__file__).parent
DEFAULT_DB = SCRIPT_DIR / "ninoxstructur.db"
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
EXTRACTOR = SCRIPT_DIR / "ninox_api_extractor.py"

# ANSI Codes - Optimiert für gute Lesbarkeit
class C:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    INVERSE = '\033[7m'
    # Vordergrundfarben
    BLACK = '\033[30m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'       # Hell-Blau für Text
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    # Hintergrundfarben
    BG_BLUE = '\033[44m'    # Dunkel-Blau Hintergrund
    BG_GRAY = '\033[100m'   # Grau Hintergrund
    # Kombinationen für Menüleiste (Weiß auf Blau = klassisch dBASE)
    MENUBAR = '\033[97m\033[44m'      # Weiß auf Blau
    MENUKEY = '\033[93m\033[44m'      # Gelb auf Blau (für F-Tasten)
    STATUSBAR = '\033[97m\033[44m'    # Weiß auf Blau

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except:
        return 80

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

def save_config(environments: dict):
    try:
        import yaml
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump({'environments': environments}, f, default_flow_style=False, allow_unicode=True)
        return True
    except:
        return False


class NinoxViewer:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        self.cur = None
        self.environments = load_config()
        self.status_msg = ""
        self.width = get_terminal_width()
        self._connect()

    def _connect(self):
        if self.db_path.exists():
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cur = self.conn.cursor()

    def _reconnect(self):
        if self.conn:
            self.conn.close()
        self._connect()

    def close(self):
        if self.conn:
            self.conn.close()

    def get_stats(self) -> dict:
        stats = {'databases': 0, 'tables': 0, 'fields': 0, 'scripts': 0, 'deps': 0}
        if not self.cur:
            return stats
        for key, table in [('databases', 'databases'), ('tables', 'tables'),
                           ('fields', 'fields'), ('scripts', 'scripts'),
                           ('deps', 'script_dependencies')]:
            try:
                self.cur.execute(f"SELECT COUNT(*) FROM {table}")
                stats[key] = self.cur.fetchone()[0]
            except:
                pass
        return stats

    # ─────────────────────────────────────────────────────────────
    # RENDERING
    # ─────────────────────────────────────────────────────────────

    def render_menubar(self):
        """Rendert die horizontale Menüleiste oben (Weiß auf Blau, Tasten in Gelb)"""
        items = [
            ("S", "Suche"),
            ("T", "Scripts"),
            ("D", "Datenbanken"),
            ("A", "Tabellen"),
            ("R", "Refresh"),
            ("C", "Config"),
            ("Q", "Ende"),
        ]
        bar = f"{C.MENUBAR} "
        for key, label in items:
            bar += f"{C.MENUKEY}{C.BOLD}{key}{C.MENUBAR} {label}  "
        # Auffüllen bis Zeilenende
        print(bar + " " * 50 + C.RESET)

    def render_statusbar(self, msg=""):
        """Rendert die Statusleiste unten (Weiß auf Blau)"""
        stats = self.get_stats()
        left = f" {stats['databases']} DBs │ {stats['tables']} Tabellen │ {stats['scripts']} Scripts"
        right = msg or self.status_msg or str(self.db_path.name)
        space = self.width - len(left) - len(right) - 2
        if space < 0:
            space = 0
        print(f"{C.STATUSBAR}{left}{' ' * space}{right} {C.RESET}")

    def render_title(self, title: str):
        """Rendert einen Abschnittstitel (Cyan Box)"""
        print(f"\n  {C.CYAN}┌{'─' * (len(title) + 2)}┐{C.RESET}")
        print(f"  {C.CYAN}│{C.RESET} {C.BOLD}{C.WHITE}{title}{C.RESET} {C.CYAN}│{C.RESET}")
        print(f"  {C.CYAN}└{'─' * (len(title) + 2)}┘{C.RESET}\n")

    def input_field(self, prompt: str, default: str = "") -> str:
        """Eingabefeld mit Prompt"""
        try:
            result = input(f"  {C.CYAN}{prompt}{C.RESET} [{default}]: ").strip()
            return result if result else default
        except (KeyboardInterrupt, EOFError):
            return ""

    def wait_key(self, msg: str = "Weiter mit beliebiger Taste..."):
        """Wartet auf Tastendruck"""
        print(f"\n  {C.DIM}{msg}{C.RESET}")
        try:
            input()
        except:
            pass

    # ─────────────────────────────────────────────────────────────
    # HAUPTMENÜ
    # ─────────────────────────────────────────────────────────────

    def run(self):
        """Hauptschleife"""
        while True:
            clear()
            self.width = get_terminal_width()
            self.render_menubar()
            self.show_main_content()
            self.render_statusbar()

            choice = self.input_field("").upper().strip()

            # Escape-Sequenzen ignorieren
            if choice.startswith('^[') or choice.startswith('\x1b'):
                continue

            if choice in ['Q', 'X', '0']:
                break
            elif choice == '':
                continue
            elif choice in ['S', '1']:
                self.search_dialog()
            elif choice in ['T', '2']:
                self.show_scripts()
            elif choice in ['D', '3']:
                self.show_databases()
            elif choice in ['A', '4']:
                self.show_tables()
            elif choice in ['R', '5']:
                self.extract_dialog()
            elif choice in ['C', '6']:
                self.config_dialog()

    def show_main_content(self):
        """Zeigt Hauptinhalt"""
        stats = self.get_stats()

        print(f"""
  {C.CYAN}╔══════════════════════════════════════════════════════════════╗
  ║{C.RESET}{C.BOLD}{C.WHITE}              N I N O X   D A T A B A S E   V I E W E R        {C.RESET}{C.CYAN}║
  ╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")
        if stats['scripts'] > 0:
            print(f"  {C.CYAN}┌─────────────────────────────────────────────────────────┐{C.RESET}")
            print(f"  {C.CYAN}│{C.RESET}  Datenbanken: {C.GREEN}{stats['databases']:>5}{C.RESET}        Scripts:    {C.GREEN}{stats['scripts']:>5}{C.RESET}       {C.CYAN}│{C.RESET}")
            print(f"  {C.CYAN}│{C.RESET}  Tabellen:    {C.GREEN}{stats['tables']:>5}{C.RESET}        Abhängigk.: {C.GREEN}{stats['deps']:>5}{C.RESET}       {C.CYAN}│{C.RESET}")
            print(f"  {C.CYAN}│{C.RESET}  Felder:      {C.GREEN}{stats['fields']:>5}{C.RESET}                              {C.CYAN}│{C.RESET}")
            print(f"  {C.CYAN}└─────────────────────────────────────────────────────────┘{C.RESET}")
        else:
            print(f"  {C.YELLOW}Keine Daten vorhanden. Drücke {C.BOLD}F5{C.RESET}{C.YELLOW} für Daten-Import.{C.RESET}")
        print()

    # ─────────────────────────────────────────────────────────────
    # F1 - SUCHE
    # ─────────────────────────────────────────────────────────────

    def search_dialog(self):
        """Suchdialog"""
        clear()
        self.render_menubar()
        self.render_title("SCRIPT-SUCHE")

        print(f"  {C.DIM}Syntax: begriff | a AND b | a OR b{C.RESET}")
        print()

        query = self.input_field("Suchbegriff")
        if not query:
            return

        self.execute_search(query)

    def execute_search(self, query: str):
        """Führt Suche aus"""
        if not self.cur:
            self.status_msg = "Keine Datenbank"
            return

        # AND/OR parsen
        terms, operator = self.parse_query(query)

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

        sql += " ORDER BY database_name, table_name LIMIT 50"

        self.cur.execute(sql, params)
        results = list(self.cur.fetchall())

        self.show_results(results, f"Suche: {query}")

    def parse_query(self, query: str):
        """Parst AND/OR Query"""
        import re
        upper = query.upper()
        if ' AND ' in upper:
            parts = re.split(r'\s+AND\s+', query, flags=re.IGNORECASE)
            return [p.strip() for p in parts], 'AND'
        elif ' OR ' in upper:
            parts = re.split(r'\s+OR\s+', query, flags=re.IGNORECASE)
            return [p.strip() for p in parts], 'OR'
        return [query.strip()], 'AND'

    def show_results(self, results: list, title: str):
        """Zeigt Suchergebnisse"""
        if not results:
            clear()
            self.render_menubar()
            print(f"\n  {C.YELLOW}Keine Treffer für: {title}{C.RESET}")
            self.wait_key()
            return

        page = 0
        per_page = 8

        while True:
            clear()
            self.render_menubar()
            self.render_title(f"{title} ({len(results)} Treffer)")

            start = page * per_page
            end = min(start + per_page, len(results))

            for i, row in enumerate(results[start:end], start=start+1):
                db = row['database_name'] or ''
                tbl = row['table_name'] or '(global)'
                elem = row['element_name'] or '-'
                typ = row['code_type']
                lines = row['line_count']

                print(f"  {C.YELLOW}{i:2}{C.RESET}. {C.CYAN}{tbl}{C.RESET} › {elem}")
                print(f"      {C.DIM}{db} | {typ} | {lines} Zeilen{C.RESET}")

            print(f"\n  {C.CYAN}─────────────────────────────────────────{C.RESET}")
            total_pages = (len(results) + per_page - 1) // per_page
            print(f"  Seite {C.WHITE}{page+1}/{total_pages}{C.RESET}  │  {C.YELLOW}N{C.RESET}=Weiter  {C.YELLOW}P{C.RESET}=Zurück  {C.YELLOW}Nr{C.RESET}=Details  {C.YELLOW}Q{C.RESET}=Ende")

            self.render_statusbar(f"{len(results)} Treffer")

            choice = self.input_field("").upper()

            if choice in ['Q', '', 'ESC']:
                break
            elif choice == 'N' and page < total_pages - 1:
                page += 1
            elif choice == 'P' and page > 0:
                page -= 1
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(results):
                    self.show_script_detail(results[idx])

    def show_script_detail(self, script):
        """Zeigt Script-Details"""
        clear()
        self.render_menubar()

        code = (script['code'] or '').replace('\\n', '\n').replace('\\t', '\t')

        self.render_title(f"{script['table_name']} › {script['element_name']}")

        print(f"  {C.DIM}Datenbank:{C.RESET} {script['database_name']}")
        print(f"  {C.DIM}Typ:{C.RESET}       {script['code_type']}")
        print(f"  {C.DIM}Zeilen:{C.RESET}    {script['line_count']}")
        print()
        print(f"  {C.DIM}{'─' * 60}{C.RESET}")

        for i, line in enumerate(code.split('\n')[:25], 1):
            print(f"  {C.DIM}{i:3}│{C.RESET} {line[:75]}")

        if len(code.split('\n')) > 25:
            print(f"  {C.DIM}    ... +{len(code.split(chr(10)))-25} weitere Zeilen{C.RESET}")

        print(f"  {C.DIM}{'─' * 60}{C.RESET}")
        self.render_statusbar()
        self.wait_key()

    # ─────────────────────────────────────────────────────────────
    # F2 - SCRIPTS
    # ─────────────────────────────────────────────────────────────

    def show_scripts(self):
        """Scripts nach Typ"""
        if not self.cur:
            return

        clear()
        self.render_menubar()
        self.render_title("SCRIPTS NACH TYP")

        self.cur.execute("""SELECT code_type, COUNT(*) as cnt
                           FROM scripts GROUP BY code_type ORDER BY cnt DESC""")
        types = list(self.cur.fetchall())

        for i, row in enumerate(types, 1):
            bar = '█' * min(row['cnt'] // 20, 25)
            print(f"  {C.YELLOW}{i:2}{C.RESET}. {row['code_type']:<20} {C.GREEN}{row['cnt']:>5}{C.RESET}  {C.DIM}{bar}{C.RESET}")

        print(f"\n  {C.DIM}Nummer eingeben für Details, {C.YELLOW}Q{C.RESET}{C.DIM}=Zurück{C.RESET}")
        self.render_statusbar()

        choice = self.input_field("").upper()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(types):
                self.cur.execute("""SELECT id, database_name, table_name, element_name,
                                    code_type, code, line_count FROM scripts
                                    WHERE code_type = ? LIMIT 50""", (types[idx]['code_type'],))
                self.show_results(list(self.cur.fetchall()), types[idx]['code_type'])

    # ─────────────────────────────────────────────────────────────
    # F3 - DATENBANKEN
    # ─────────────────────────────────────────────────────────────

    def show_databases(self):
        """Zeigt Datenbanken"""
        if not self.cur:
            return

        clear()
        self.render_menubar()
        self.render_title("DATENBANKEN")

        self.cur.execute("SELECT id, name, table_count, code_count FROM databases ORDER BY name")

        for row in self.cur.fetchall():
            print(f"  {C.CYAN}■{C.RESET} {C.BOLD}{row['name']}{C.RESET}")
            print(f"    {C.DIM}Tabellen: {row['table_count']}  Scripts: {row['code_count']}{C.RESET}")

        self.render_statusbar()
        self.wait_key()

    # ─────────────────────────────────────────────────────────────
    # F4 - TABELLEN
    # ─────────────────────────────────────────────────────────────

    def show_tables(self):
        """Zeigt Tabellen"""
        if not self.cur:
            return

        clear()
        self.render_menubar()
        self.render_title("TABELLEN")

        self.cur.execute("""SELECT t.name, t.caption, t.field_count, d.name as db_name
                           FROM tables t JOIN databases d ON t.database_id = d.id
                           ORDER BY d.name, t.name LIMIT 50""")

        current_db = None
        for row in self.cur.fetchall():
            if current_db != row['db_name']:
                current_db = row['db_name']
                print(f"\n  {C.CYAN}{C.BOLD}[{current_db}]{C.RESET}")
            caption = f" ({row['caption']})" if row['caption'] and row['caption'] != row['name'] else ""
            print(f"    ├─ {row['name']}{C.DIM}{caption} [{row['field_count']} Felder]{C.RESET}")

        self.render_statusbar()
        self.wait_key()

    # ─────────────────────────────────────────────────────────────
    # F5 - DATEN ABRUFEN
    # ─────────────────────────────────────────────────────────────

    def extract_dialog(self):
        """Dialog für Datenextraktion"""
        if not self.environments:
            self.status_msg = "Keine Config - F6 drücken"
            return

        clear()
        self.render_menubar()
        self.render_title("DATEN AUS NINOX ABRUFEN")

        envs = list(self.environments.keys())
        for i, name in enumerate(envs, 1):
            env = self.environments[name]
            print(f"  {C.YELLOW}{i}{C.RESET}. {C.BOLD}{name}{C.RESET} - {env.get('teamName', '')}")

        print(f"  {C.YELLOW}A{C.RESET}. Alle Teams")
        print()

        self.render_statusbar()
        choice = self.input_field("Team auswählen").upper()

        if choice == 'A':
            self.run_extraction(envs)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(envs):
                self.run_extraction([envs[idx]])

    def run_extraction(self, env_names: list):
        """Führt Extraktion aus"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cur = None
            time.sleep(0.2)

        clear()
        self.render_menubar()
        self.render_title("EXTRAKTION")

        for env_name in env_names:
            print(f"  {C.YELLOW}►{C.RESET} Extrahiere {C.BOLD}{env_name}{C.RESET}...")

            cmd = [sys.executable, str(EXTRACTOR), 'extract',
                   '--config', str(CONFIG_FILE), '--env', env_name,
                   '--db', str(self.db_path)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
                if result.returncode == 0:
                    print(f"  {C.GREEN}✓{C.RESET} Erfolgreich")
                    for line in result.stdout.split('\n'):
                        if 'databases:' in line or 'scripts:' in line:
                            print(f"    {C.DIM}{line.strip()}{C.RESET}")
                else:
                    print(f"  {C.RED}✗{C.RESET} Fehler")
                    for line in (result.stderr or result.stdout).strip().split('\n')[-5:]:
                        print(f"    {C.RED}{line}{C.RESET}")
            except Exception as e:
                print(f"  {C.RED}✗{C.RESET} {e}")

        self._reconnect()
        self.render_statusbar("Extraktion abgeschlossen")
        self.wait_key()

    # ─────────────────────────────────────────────────────────────
    # F6 - KONFIGURATION
    # ─────────────────────────────────────────────────────────────

    def config_dialog(self):
        """Konfigurationsdialog"""
        clear()
        self.render_menubar()
        self.render_title("KONFIGURATION")

        if self.environments:
            print(f"  {C.DIM}Vorhandene Environments:{C.RESET}")
            for name, env in self.environments.items():
                print(f"  {C.CYAN}■{C.RESET} {C.BOLD}{name}{C.RESET}: {env.get('domain', '')}")
            print()

        print(f"  {C.YELLOW}N{C.RESET} = Neues Environment anlegen")
        print(f"  {C.YELLOW}Q{C.RESET} = Zurück")
        print()

        self.render_statusbar()
        choice = self.input_field("").upper()

        if choice == 'N':
            self.create_environment()

    def create_environment(self):
        """Erstellt neues Environment"""
        clear()
        self.render_menubar()
        self.render_title("NEUES ENVIRONMENT")

        print(f"  {C.DIM}Ninox Zugangsdaten eingeben:{C.RESET}\n")

        name = self.input_field("Name (z.B. production)")
        if not name:
            return

        domain = self.input_field("Domain", "https://app.ninoxdb.de")
        if not domain.startswith('http'):
            domain = 'https://' + domain

        workspace_id = self.input_field("Workspace-ID")
        if not workspace_id:
            return

        team_name = self.input_field("Team-Name", name.capitalize())

        api_key = self.input_field("API-Key")
        if not api_key:
            return

        self.environments[name] = {
            'domain': domain,
            'workspaceId': workspace_id,
            'teamName': team_name,
            'apiKey': api_key
        }

        if save_config(self.environments):
            print(f"\n  {C.GREEN}✓ Gespeichert!{C.RESET}")
        else:
            print(f"\n  {C.RED}✗ Fehler beim Speichern{C.RESET}")

        self.wait_key()


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
