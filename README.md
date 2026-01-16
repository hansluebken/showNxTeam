# Ninox API Extractor

CLI-Tool zur Extraktion und Analyse von Ninox-Datenbankstrukturen über die REST API. Extrahiert Schemas, Skripte, Formeln und Beziehungen und speichert diese in einer SQLite-Datenbank für Suche, Analyse und Dokumentation.

## Features

- **Schema-Extraktion**: Tabellen, Felder, Beziehungen aus der Ninox API
- **Code-Extraktion**: Trigger, Formeln, Buttons, Berechtigungen, globale Funktionen
- **Code-Übersetzung**: Automatische Übersetzung von Feld-IDs zu lesbaren Namen
- **Volltextsuche**: FTS5-basierte Suche in allen Skripten
- **Abhängigkeitsanalyse**: Zeigt Tabellenbeziehungen und Referenzen
- **Export**: JSON, HTML (mit Syntax-Highlighting), Markdown-Dokumentation

## Installation

### Voraussetzungen

- Python 3.8+
- Ninox API-Zugang (API-Key)

### Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

Oder manuell:

```bash
pip install requests pyyaml python-dotenv
```

### Dateien

| Datei | Beschreibung |
|-------|--------------|
| `ninox_api_extractor.py` | Hauptprogramm (CLI) |
| `ninox_lexer.py` | Syntax-Highlighting & Code-Formatierung |
| `ninox_yaml_parser.py` | Parser für ninox-dev-cli YAML-Struktur |
| `ninox_md_generator.py` | Markdown-Generator für Backups |
| `showNxTeam.py` | Interaktive Datenbank-Ansicht |

## Konfiguration

Zugangsdaten können auf drei Wegen bereitgestellt werden (Priorität absteigend):

### 1. CLI-Argumente

```bash
python3 ninox_api_extractor.py extract \
    --domain https://app.ninox.com \
    --team TEAM_ID \
    --apikey YOUR_API_KEY
```

### 2. Config-Datei (YAML)

```yaml
# config.yaml
environments:
  production:
    domain: https://app.ninox.com
    workspaceId: abc123
    apiKey: your-api-key
  development:
    domain: https://dev.ninox.com
    workspaceId: xyz789
    apiKey: dev-api-key
```

```bash
python3 ninox_api_extractor.py extract --config config.yaml --env production
```

### 3. Umgebungsvariablen

Erstelle eine `.env` Datei (siehe `.env.example`):

```env
NINOX_DOMAIN=https://app.ninox.com
NINOX_TEAM_ID=your-team-id
NINOX_API_KEY=your-api-key
```

## Befehle

### `extract` - Schema und Skripte extrahieren

```bash
# Alle Datenbanken extrahieren
python3 ninox_api_extractor.py extract --domain https://app.ninox.com \
    --team TEAM_ID --apikey API_KEY --db output.db

# Nur bestimmte Datenbanken
python3 ninox_api_extractor.py extract --domain https://app.ninox.com \
    --team TEAM_ID --apikey API_KEY --databases db1,db2

# Mit Config-Datei
python3 ninox_api_extractor.py extract --config config.yaml --env dev
```

### `search` - Volltextsuche in Skripten

```bash
# Einfache Suche
python3 ninox_api_extractor.py search "select Kunden" --db output.db

# Mit Filtern
python3 ninox_api_extractor.py search "http(" --type onClick --db output.db
python3 ninox_api_extractor.py search "Auftrag" --table Bestellungen --db output.db

# Code anzeigen
python3 ninox_api_extractor.py search "sendEmail" --show-code --db output.db
```

### `deps` - Tabellenabhängigkeiten anzeigen

```bash
python3 ninox_api_extractor.py deps "Aufträge" --db output.db
```

Zeigt:
- Referenzierte Tabellen (N:1)
- Rückverweise von anderen Tabellen (1:N)
- Formel-Referenzen

### `stats` - Statistiken anzeigen

```bash
python3 ninox_api_extractor.py stats --db output.db
```

Ausgabe:
- Anzahl Datenbanken, Tabellen, Felder
- Scripts nach Typ
- Beziehungen nach Typ
- Top-Tabellen nach Script-Anzahl

### `list` - Datenbanken und Tabellen auflisten

```bash
# Alle Datenbanken
python3 ninox_api_extractor.py list --db output.db

# Tabellen einer Datenbank
python3 ninox_api_extractor.py list --database "ERP System" --db output.db
```

### `export` - JSON-Export

```bash
python3 ninox_api_extractor.py export schema.json --db output.db
```

### `html` - HTML-Export mit Syntax-Highlighting

```bash
python3 ninox_api_extractor.py html scripts.html --db output.db

# Nur eine Datenbank
python3 ninox_api_extractor.py html erp.html --database "ERP System" --db output.db
```

### `md` - Markdown-Dokumentation generieren

```bash
# Vollständige Dokumentation
python3 ninox_api_extractor.py md dokumentation.md --db output.db

# Nur eine Datenbank
python3 ninox_api_extractor.py md erp_doku.md --database "ERP System" --db output.db
```

Die Markdown-Dokumentation enthält:
- Inhaltsverzeichnis
- Alle Tabellen mit Feldern
- Alle Skripte mit Code
- Beziehungen zwischen Tabellen

## Interaktive Datenbank-Ansicht

Das `showNxTeam.py` Skript bietet eine interaktive Ansicht der extrahierten Daten:

```bash
# Starten (ausführbar ohne python3)
./showNxTeam.py

# Mit eigener Datenbank
./showNxTeam.py meine_datenbank.db
```

Navigation in der Skript-Ansicht:
- `n` - Nächste Seite
- `p` - Vorherige Seite
- `g` - Gehe zu Seite
- `q` - Beenden

## SQLite-Datenbankschema

Die extrahierten Daten werden in folgenden Tabellen gespeichert:

| Tabelle | Beschreibung |
|---------|--------------|
| `databases` | Datenbank-Metadaten |
| `tables` | Tabellendefinitionen |
| `fields` | Feld/Spalten-Definitionen |
| `relationships` | Tabellenbeziehungen |
| `scripts` | Extrahierter Code |
| `scripts_fts` | FTS5 Volltextsuche-Index |

### Beziehungstypen

| Typ | Beschreibung |
|-----|--------------|
| `N_TO_1` | Viele-zu-Eins (Referenzfeld) |
| `ONE_TO_N` | Eins-zu-Viele (inverse Seite) |
| `M_TO_N` | Viele-zu-Viele |
| `CROSS_DATABASE` | Datenbankübergreifend |
| `FORMULA_REFERENCE` | Referenz aus Formelcode |

### Code-Kategorien

| Kategorie | Beschreibung |
|-----------|--------------|
| `TRIGGER` | Trigger-Skripte (afterCreate, afterUpdate, etc.) |
| `FORMULA` | Berechnungsformeln (fn) |
| `BUTTON` | Button-Aktionen (onClick) |
| `PERMISSION` | Berechtigungsformeln (canRead, canWrite) |
| `GLOBAL_FUNCTION` | Globale Funktionen (globalCode) |
| `PRINT_TEMPLATE` | Druckvorlagen |

## Ninox Lexer

Der `ninox_lexer.py` bietet Syntax-Highlighting und Code-Formatierung:

```python
from ninox_lexer import format_code, highlight_code, tokenize

# Code formatieren (Einrückung)
formatted = format_code(ninox_code)

# HTML mit Syntax-Highlighting
html = highlight_code(ninox_code, show_line_numbers=True)

# Tokenisieren
tokens = tokenize(ninox_code)
```

### Unterstützte Token-Typen

- Keywords: `if`, `then`, `else`, `let`, `var`, `for`, `while`, `do`, `end`, `select`, `where`, etc.
- Built-in Funktionen: `record`, `create`, `sum`, `avg`, `http`, `sendEmail`, etc.
- Strings, Zahlen, Kommentare
- Tabellen- und Feld-IDs

## Beispiel-Workflow

```bash
# 1. Daten extrahieren
python3 ninox_api_extractor.py extract \
    --domain https://app.ninox.com \
    --team abc123 \
    --apikey your-key \
    --db ninox.db

# 2. Statistiken prüfen
python3 ninox_api_extractor.py stats --db ninox.db

# 3. Nach Code suchen
python3 ninox_api_extractor.py search "http(" --db ninox.db

# 4. Dokumentation erstellen
python3 ninox_api_extractor.py md dokumentation.md --db ninox.db

# 5. Interaktiv durchsuchen
./showNxTeam.py
```

## Lizenz

MIT License

## Autor

Erstellt für die Analyse und Dokumentation von Ninox-Datenbanken.
