# Ninox API Extractor - Integrationsspezifikation

Diese Spezifikation beschreibt die Integration des Ninox API Extractors in eine bestehende Anwendung mit PostgreSQL und Redis sowie die Anbindung an KI-Systeme für Chat-basierte Abfragen.

---

## Teil 1: PostgreSQL + Redis Integration

### 1.1 Ausgangslage

Der Ninox API Extractor extrahiert Skripte und Schemas aus Ninox-Datenbanken über die REST API. Die Daten haben folgende Struktur:

```
Team (team_id, team_name)
  └── Database (database_id, database_name)
       └── Table (table_id, table_name)
            └── Element (element_id, element_name)
                 └── Script (code_type, code_category, code)
                      └── Dependencies (target_database, reference_type)
```

**Cross-Database-Referenzen:**
Scripts können auf andere Datenbanken verweisen. Diese Abhängigkeiten werden separat in `script_dependencies` gespeichert:
- `do as database 'Datenbankname'` - Explizite Datenbank-Referenz
- `do as server` - Server-seitige Ausführung
- `openDatabase('Datenbankname')` - Datenbank öffnen

**Extrahierte Code-Typen:**
- `globalCode` - Globaler Datenbankcode
- `afterCreate`, `afterUpdate`, `beforeDelete` - Trigger
- `fn` - Formelfelder
- `onClick` - Button-Handler
- `canRead`, `canWrite`, `canCreate`, `canDelete` - Berechtigungen
- `validation`, `constraint` - Validierungen
- `dchoiceValues`, `dchoiceCaption` - Dynamische Auswahlfelder

### 1.2 PostgreSQL Schema

#### 1.2.1 Erforderliche Extensions

```sql
-- Für Volltextsuche mit deutschen Wörtern
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Für Vektorsuche (KI-Integration, siehe Teil 2)
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 1.2.2 Tabellen

```sql
-- Teams/Workspaces
CREATE TABLE ninox_teams (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Datenbanken
CREATE TABLE ninox_databases (
    id VARCHAR(50) PRIMARY KEY,
    team_id VARCHAR(50) NOT NULL REFERENCES ninox_teams(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    schema_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabellen
CREATE TABLE ninox_tables (
    id VARCHAR(50) NOT NULL,
    database_id VARCHAR(50) NOT NULL REFERENCES ninox_databases(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    caption VARCHAR(255),
    field_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (database_id, id)
);

-- Scripts (Haupttabelle für Suche)
CREATE TABLE ninox_scripts (
    id SERIAL PRIMARY KEY,

    -- Hierarchie
    team_id VARCHAR(50) NOT NULL,
    team_name VARCHAR(255),
    database_id VARCHAR(50) NOT NULL,
    database_name VARCHAR(255),
    table_id VARCHAR(50),
    table_name VARCHAR(255),
    element_id VARCHAR(50),
    element_name VARCHAR(255),

    -- Script-Metadaten
    code_type VARCHAR(50) NOT NULL,
    code_category VARCHAR(50),
    code TEXT NOT NULL,
    line_count INTEGER DEFAULT 0,

    -- Zeitstempel
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique Constraint für Upsert
    CONSTRAINT uq_script_location UNIQUE (database_id, table_id, element_id, code_type)
);

-- Volltext-Suchindex (separater Trigger-basierter Ansatz für Flexibilität)
ALTER TABLE ninox_scripts ADD COLUMN search_vector TSVECTOR;

CREATE INDEX idx_scripts_search ON ninox_scripts USING GIN(search_vector);
CREATE INDEX idx_scripts_team ON ninox_scripts(team_id);
CREATE INDEX idx_scripts_database ON ninox_scripts(database_id);
CREATE INDEX idx_scripts_table ON ninox_scripts(table_id);
CREATE INDEX idx_scripts_type ON ninox_scripts(code_type);
CREATE INDEX idx_scripts_category ON ninox_scripts(code_category);

-- Trigram-Index für LIKE/ILIKE Suchen und Fuzzy-Matching
CREATE INDEX idx_scripts_code_trgm ON ninox_scripts USING GIN(code gin_trgm_ops);
CREATE INDEX idx_scripts_element_trgm ON ninox_scripts USING GIN(element_name gin_trgm_ops);

-- Cross-Database-Abhängigkeiten
CREATE TABLE ninox_script_dependencies (
    id SERIAL PRIMARY KEY,
    script_id INTEGER NOT NULL REFERENCES ninox_scripts(id) ON DELETE CASCADE,
    source_database_id VARCHAR(50) NOT NULL,
    source_database_name VARCHAR(255),
    target_database_name VARCHAR(255) NOT NULL,
    reference_type VARCHAR(50) NOT NULL,
    code_snippet TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT chk_reference_type CHECK (
        reference_type IN ('do as database', 'do as server', 'openDatabase')
    )
);

CREATE INDEX idx_dependencies_script ON ninox_script_dependencies(script_id);
CREATE INDEX idx_dependencies_source ON ninox_script_dependencies(source_database_name);
CREATE INDEX idx_dependencies_target ON ninox_script_dependencies(target_database_name);
CREATE INDEX idx_dependencies_type ON ninox_script_dependencies(reference_type);
```

#### 1.2.3 Trigger für Suchvektor

```sql
-- Funktion zum Aktualisieren des Suchvektors
CREATE OR REPLACE FUNCTION update_script_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', COALESCE(NEW.team_name, '')), 'D') ||
        setweight(to_tsvector('simple', COALESCE(NEW.database_name, '')), 'C') ||
        setweight(to_tsvector('simple', COALESCE(NEW.table_name, '')), 'B') ||
        setweight(to_tsvector('simple', COALESCE(NEW.element_name, '')), 'A') ||
        setweight(to_tsvector('simple', COALESCE(NEW.code, '')), 'B');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger bei INSERT und UPDATE
CREATE TRIGGER trg_scripts_search_vector
    BEFORE INSERT OR UPDATE ON ninox_scripts
    FOR EACH ROW
    EXECUTE FUNCTION update_script_search_vector();
```

#### 1.2.4 Hilfreiche Views

```sql
-- View für einfache Script-Suche mit Kontext
CREATE VIEW v_scripts_searchable AS
SELECT
    s.id,
    s.team_name || ' > ' || s.database_name || ' > ' ||
        COALESCE(s.table_name, '(Global)') || ' > ' ||
        COALESCE(s.element_name, '(Tabelle)') AS full_path,
    s.code_type,
    s.code_category,
    s.code,
    s.line_count,
    s.team_id,
    s.database_id,
    s.table_id,
    s.element_id
FROM ninox_scripts s;

-- View für Statistiken pro Team
CREATE VIEW v_team_statistics AS
SELECT
    team_id,
    team_name,
    COUNT(DISTINCT database_id) AS database_count,
    COUNT(DISTINCT table_id) FILTER (WHERE table_id IS NOT NULL) AS table_count,
    COUNT(*) AS script_count,
    SUM(line_count) AS total_lines,
    jsonb_object_agg(code_category, category_count) AS scripts_by_category
FROM (
    SELECT
        team_id, team_name, database_id, table_id,
        code_category, line_count,
        COUNT(*) OVER (PARTITION BY team_id, code_category) AS category_count
    FROM ninox_scripts
) sub
GROUP BY team_id, team_name;

-- View für Cross-Database-Abhängigkeiten mit Script-Kontext
CREATE VIEW v_database_dependencies AS
SELECT
    d.id AS dependency_id,
    d.source_database_name,
    d.target_database_name,
    d.reference_type,
    s.table_name,
    s.element_name,
    s.code_type,
    d.code_snippet,
    s.id AS script_id
FROM ninox_script_dependencies d
JOIN ninox_scripts s ON d.script_id = s.id;

-- View für Dependency-Matrix (Aggregiert)
CREATE VIEW v_dependency_matrix AS
SELECT
    source_database_name AS source_db,
    target_database_name AS target_db,
    reference_type,
    COUNT(*) AS reference_count,
    array_agg(DISTINCT table_name) FILTER (WHERE table_name IS NOT NULL) AS tables_involved
FROM v_database_dependencies
GROUP BY source_database_name, target_database_name, reference_type
ORDER BY reference_count DESC;
```

### 1.3 Redis Caching-Strategie

#### 1.3.1 Key-Namenskonvention

```
ninox:{ressource}:{identifier}:{sub-identifier}
```

#### 1.3.2 Cache-Keys und TTL

| Key-Pattern | Inhalt | TTL | Invalidierung |
|-------------|--------|-----|---------------|
| `ninox:search:{team_id}:{query_hash}` | Suchergebnisse (JSON Array) | 300s (5 min) | Bei neuer Extraktion |
| `ninox:schema:{database_id}` | Datenbank-Schema (JSON) | 3600s (1 h) | Bei neuer Extraktion |
| `ninox:scripts:{table_id}` | Scripts einer Tabelle (JSON Array) | 600s (10 min) | Bei neuer Extraktion |
| `ninox:stats:{team_id}` | Team-Statistiken (JSON) | 1800s (30 min) | Bei neuer Extraktion |
| `ninox:api:{endpoint_hash}` | API-Response Cache (JSON) | 300s (5 min) | Automatisch (TTL) |

#### 1.3.3 Cache-Implementierungsregeln

1. **Cache-Aside Pattern**: Erst Cache prüfen, bei Miss aus DB laden und Cache füllen
2. **Write-Through bei Extraktion**: Nach erfolgreicher Extraktion relevante Caches invalidieren
3. **Query-Hash**: MD5 oder SHA256 des normalisierten Query-Strings (lowercase, trimmed)
4. **Serialisierung**: JSON mit kompakter Formatierung (kein Pretty-Print)

#### 1.3.4 Invalidierungs-Events

```
Event: extraction_complete
  → Lösche: ninox:search:{team_id}:*
  → Lösche: ninox:stats:{team_id}
  → Lösche: ninox:scripts:{table_id} für alle betroffenen Tabellen

Event: database_deleted
  → Lösche: ninox:schema:{database_id}
  → Lösche: ninox:scripts:{table_id} für alle Tabellen der DB
```

### 1.4 Such-Queries

#### 1.4.1 Volltextsuche (schnell, für einzelne Wörter)

```sql
SELECT id, full_path, code_type, code,
       ts_rank(search_vector, query) AS relevance
FROM ninox_scripts, plainto_tsquery('simple', $1) query
WHERE team_id = $2
  AND search_vector @@ query
ORDER BY relevance DESC
LIMIT 50;
```

#### 1.4.2 Trigram-Suche (fuzzy, für Teilstrings und Tippfehler)

```sql
SELECT id, full_path, code_type, code,
       similarity(code, $1) AS relevance
FROM ninox_scripts
WHERE team_id = $2
  AND code % $1  -- Trigram-Ähnlichkeit
ORDER BY relevance DESC
LIMIT 50;
```

#### 1.4.3 Kombinierte Suche (LIKE für exakte Muster)

```sql
SELECT id, full_path, code_type, code
FROM ninox_scripts
WHERE team_id = $1
  AND code ILIKE '%' || $2 || '%'
ORDER BY
    CASE WHEN element_name ILIKE '%' || $2 || '%' THEN 0 ELSE 1 END,
    table_name, element_name
LIMIT 50;
```

### 1.5 API-Endpunkte (Empfehlung)

| Methode | Endpunkt | Beschreibung |
|---------|----------|--------------|
| POST | `/api/ninox/extract` | Startet Extraktion für ein Team |
| GET | `/api/ninox/search?q={query}&team={id}` | Durchsucht Scripts |
| GET | `/api/ninox/scripts/{id}` | Einzelnes Script mit Kontext |
| GET | `/api/ninox/databases/{id}/scripts` | Alle Scripts einer DB |
| GET | `/api/ninox/tables/{id}/scripts` | Alle Scripts einer Tabelle |
| GET | `/api/ninox/stats/{team_id}` | Statistiken |
| GET | `/api/ninox/dependencies` | Alle Cross-DB-Abhängigkeiten |
| GET | `/api/ninox/dependencies/matrix` | Dependency-Matrix (aggregiert) |
| GET | `/api/ninox/databases/{id}/dependencies` | Abhängigkeiten einer DB |

---

## Teil 2: KI-Integration für Chat-basierte Abfragen

### 2.1 Architektur-Optionen

Es gibt drei Hauptansätze, um die Ninox-Daten für KI-Chat-Abfragen verfügbar zu machen:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Option A: Function Calling                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User ──► LLM ──► Function Call ──► PostgreSQL ──► LLM ──► User   │
│                    (search_scripts)                                 │
│                                                                     │
│   Vorteile: Exakte Suche, strukturierte Daten, deterministisch     │
│   Nachteile: LLM muss richtige Funktion/Parameter wählen           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Option B: RAG mit Embeddings                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User Query ──► Embedding ──► Vector Search ──► Context ──► LLM   │
│                                 (pgvector)                          │
│                                                                     │
│   Vorteile: Semantische Suche, findet ähnliche Konzepte            │
│   Nachteile: Mehr Infrastruktur, Embedding-Kosten                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Option C: Hybrid (Empfohlen)                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User ──► LLM ──► Function Call ──┬──► Keyword Search (FTS)       │
│                                    └──► Semantic Search (Vector)    │
│                                              │                      │
│                                              ▼                      │
│                                    Merged Results ──► LLM ──► User  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Option A: Function Calling (Tool Use)

#### 2.2.1 Tool-Definitionen für Claude/OpenAI

```json
{
  "tools": [
    {
      "name": "search_ninox_scripts",
      "description": "Durchsucht alle Ninox-Scripts nach Code, Funktionen, Triggern oder Formeln. Verwende diese Funktion wenn der Benutzer nach spezifischem Code, Feldnamen, Tabellennamen oder Funktionalität in Ninox fragt.",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Suchbegriff: Feldname, Funktionsname, Code-Fragment oder Beschreibung"
          },
          "code_type": {
            "type": "string",
            "enum": ["afterCreate", "afterUpdate", "beforeDelete", "fn", "onClick", "globalCode", "validation", "constraint", "canRead", "canWrite"],
            "description": "Optional: Filtert nach Script-Typ"
          },
          "table_name": {
            "type": "string",
            "description": "Optional: Filtert nach Tabellenname"
          },
          "limit": {
            "type": "integer",
            "default": 10,
            "description": "Maximale Anzahl Ergebnisse"
          }
        },
        "required": ["query"]
      }
    },
    {
      "name": "get_table_structure",
      "description": "Zeigt die Struktur einer Ninox-Tabelle mit allen Feldern, Triggern und Beziehungen.",
      "input_schema": {
        "type": "object",
        "properties": {
          "table_name": {
            "type": "string",
            "description": "Name der Tabelle"
          }
        },
        "required": ["table_name"]
      }
    },
    {
      "name": "list_ninox_tables",
      "description": "Listet alle Tabellen einer Ninox-Datenbank auf.",
      "input_schema": {
        "type": "object",
        "properties": {
          "database_name": {
            "type": "string",
            "description": "Optional: Name der Datenbank"
          }
        }
      }
    },
    {
      "name": "get_script_details",
      "description": "Zeigt den vollständigen Code eines Scripts mit Kontext.",
      "input_schema": {
        "type": "object",
        "properties": {
          "script_id": {
            "type": "integer",
            "description": "ID des Scripts"
          }
        },
        "required": ["script_id"]
      }
    },
    {
      "name": "find_field_usage",
      "description": "Findet alle Stellen, an denen ein bestimmtes Feld verwendet wird.",
      "input_schema": {
        "type": "object",
        "properties": {
          "field_name": {
            "type": "string",
            "description": "Name des Feldes"
          }
        },
        "required": ["field_name"]
      }
    },
    {
      "name": "get_database_dependencies",
      "description": "Zeigt alle Cross-Database-Abhängigkeiten. Findet heraus, welche Datenbanken auf welche anderen Datenbanken zugreifen (do as database, do as server, openDatabase).",
      "input_schema": {
        "type": "object",
        "properties": {
          "database_name": {
            "type": "string",
            "description": "Optional: Filtert nach Quell- oder Ziel-Datenbank"
          },
          "direction": {
            "type": "string",
            "enum": ["outgoing", "incoming", "both"],
            "default": "both",
            "description": "outgoing=von dieser DB ausgehend, incoming=auf diese DB zeigend, both=beides"
          }
        }
      }
    },
    {
      "name": "get_dependency_matrix",
      "description": "Zeigt eine Übersicht aller Datenbank-Abhängigkeiten als Matrix. Nützlich um zu verstehen, wie Datenbanken miteinander verbunden sind.",
      "input_schema": {
        "type": "object",
        "properties": {}
      }
    }
  ]
}
```

#### 2.2.2 Tool-Handler Implementierung

```python
def handle_tool_call(tool_name: str, params: dict, db_conn, redis_client) -> str:
    """
    Verarbeitet Tool-Aufrufe vom LLM.
    Gibt JSON-String zurück, der als Tool-Response an das LLM gesendet wird.
    """

    if tool_name == "search_ninox_scripts":
        return search_scripts(
            query=params["query"],
            code_type=params.get("code_type"),
            table_name=params.get("table_name"),
            limit=params.get("limit", 10),
            db_conn=db_conn,
            redis=redis_client
        )

    elif tool_name == "get_table_structure":
        return get_table_structure(
            table_name=params["table_name"],
            db_conn=db_conn
        )

    elif tool_name == "list_ninox_tables":
        return list_tables(
            database_name=params.get("database_name"),
            db_conn=db_conn
        )

    elif tool_name == "get_database_dependencies":
        return get_database_dependencies(
            database_name=params.get("database_name"),
            direction=params.get("direction", "both"),
            db_conn=db_conn
        )

    elif tool_name == "get_dependency_matrix":
        return get_dependency_matrix(db_conn=db_conn)

    # ... weitere Handler


def get_database_dependencies(database_name, direction, db_conn) -> str:
    """Holt Cross-Database-Abhängigkeiten."""

    sql = """
        SELECT
            source_database_name,
            target_database_name,
            reference_type,
            table_name,
            element_name,
            code_snippet
        FROM v_database_dependencies
        WHERE 1=1
    """
    params = []

    if database_name:
        if direction == "outgoing":
            sql += " AND source_database_name ILIKE %s"
            params.append(f"%{database_name}%")
        elif direction == "incoming":
            sql += " AND target_database_name ILIKE %s"
            params.append(f"%{database_name}%")
        else:  # both
            sql += " AND (source_database_name ILIKE %s OR target_database_name ILIKE %s)"
            params.extend([f"%{database_name}%", f"%{database_name}%"])

    sql += " ORDER BY source_database_name, target_database_name LIMIT 50"

    with db_conn.cursor() as cur:
        cur.execute(sql, params)
        results = cur.fetchall()

    response = {
        "found": len(results),
        "dependencies": [
            {
                "from": r[0],
                "to": r[1],
                "type": r[2],
                "table": r[3],
                "element": r[4],
                "snippet": r[5]
            }
            for r in results
        ]
    }

    return json.dumps(response, ensure_ascii=False)


def get_dependency_matrix(db_conn) -> str:
    """Holt aggregierte Dependency-Matrix."""

    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT source_db, target_db, reference_type,
                   reference_count, tables_involved
            FROM v_dependency_matrix
            ORDER BY reference_count DESC
        """)
        results = cur.fetchall()

    response = {
        "total_connections": len(results),
        "matrix": [
            {
                "from": r[0],
                "to": r[1],
                "type": r[2],
                "count": r[3],
                "tables": r[4]
            }
            for r in results
        ]
    }

    return json.dumps(response, ensure_ascii=False)


def search_scripts(query, code_type, table_name, limit, db_conn, redis) -> str:
    """Sucht Scripts und gibt formatiertes Ergebnis zurück."""

    # Cache prüfen
    cache_key = f"ninox:search:{hash(f'{query}:{code_type}:{table_name}')}"
    cached = redis.get(cache_key)
    if cached:
        return cached

    # SQL Query bauen
    sql = """
        SELECT
            id,
            database_name,
            table_name,
            element_name,
            code_type,
            code_category,
            CASE
                WHEN LENGTH(code) > 500 THEN SUBSTRING(code, 1, 500) || '...'
                ELSE code
            END AS code_preview,
            line_count
        FROM ninox_scripts
        WHERE search_vector @@ plainto_tsquery('simple', %s)
    """
    params = [query]

    if code_type:
        sql += " AND code_type = %s"
        params.append(code_type)

    if table_name:
        sql += " AND table_name ILIKE %s"
        params.append(f"%{table_name}%")

    sql += " ORDER BY ts_rank(search_vector, plainto_tsquery('simple', %s)) DESC LIMIT %s"
    params.extend([query, limit])

    # Ausführen
    with db_conn.cursor() as cur:
        cur.execute(sql, params)
        results = cur.fetchall()

    # Formatieren
    response = {
        "found": len(results),
        "scripts": [
            {
                "id": r[0],
                "location": f"{r[1]} > {r[2] or '(Global)'} > {r[3] or '(Tabelle)'}",
                "type": r[4],
                "category": r[5],
                "code": r[6],
                "lines": r[7]
            }
            for r in results
        ]
    }

    result_json = json.dumps(response, ensure_ascii=False)
    redis.setex(cache_key, 300, result_json)

    return result_json
```

### 2.3 Option B: RAG mit Vector Embeddings

#### 2.3.1 Schema-Erweiterung für Embeddings

```sql
-- Embedding-Spalte hinzufügen (1536 Dimensionen für OpenAI, 1024 für andere)
ALTER TABLE ninox_scripts
ADD COLUMN embedding vector(1536);

-- Index für schnelle Ähnlichkeitssuche
CREATE INDEX idx_scripts_embedding ON ninox_scripts
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

#### 2.3.2 Embedding-Generierung

```python
def generate_script_embedding(script: dict, embedding_client) -> list:
    """
    Generiert ein Embedding für ein Script.
    Der Text wird so strukturiert, dass er maximalen Kontext enthält.
    """

    # Kontextreicher Text für Embedding
    text = f"""
    Ninox Script in Tabelle "{script['table_name'] or 'Global'}"
    Element: {script['element_name'] or 'Tabellen-Trigger'}
    Typ: {script['code_type']} ({script['code_category']})

    Code:
    {script['code']}
    """.strip()

    # Embedding generieren (OpenAI Beispiel)
    response = embedding_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )

    return response.data[0].embedding


def index_all_scripts(db_conn, embedding_client):
    """Generiert Embeddings für alle Scripts ohne Embedding."""

    with db_conn.cursor() as cur:
        # Scripts ohne Embedding laden
        cur.execute("""
            SELECT id, table_name, element_name, code_type,
                   code_category, code
            FROM ninox_scripts
            WHERE embedding IS NULL
        """)
        scripts = cur.fetchall()

        for script in scripts:
            script_dict = {
                'table_name': script[1],
                'element_name': script[2],
                'code_type': script[3],
                'code_category': script[4],
                'code': script[5]
            }

            embedding = generate_script_embedding(script_dict, embedding_client)

            cur.execute("""
                UPDATE ninox_scripts
                SET embedding = %s
                WHERE id = %s
            """, (embedding, script[0]))

        db_conn.commit()
```

#### 2.3.3 Semantische Suche

```sql
-- Funktion für semantische Suche
CREATE OR REPLACE FUNCTION search_scripts_semantic(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    id int,
    full_path text,
    code_type varchar,
    code text,
    similarity float
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.team_name || ' > ' || s.database_name || ' > ' ||
            COALESCE(s.table_name, '(Global)') || ' > ' ||
            COALESCE(s.element_name, '(Tabelle)'),
        s.code_type,
        s.code,
        1 - (s.embedding <=> query_embedding) AS similarity
    FROM ninox_scripts s
    WHERE 1 - (s.embedding <=> query_embedding) > match_threshold
    ORDER BY s.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
```

#### 2.3.4 RAG Pipeline

```python
def rag_query(user_question: str, db_conn, embedding_client, llm_client) -> str:
    """
    Vollständige RAG-Pipeline für Ninox-Fragen.
    """

    # 1. Query-Embedding generieren
    query_embedding = embedding_client.embeddings.create(
        model="text-embedding-3-small",
        input=user_question
    ).data[0].embedding

    # 2. Ähnliche Scripts finden
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM search_scripts_semantic(%s::vector, 0.6, 5)
        """, (query_embedding,))
        relevant_scripts = cur.fetchall()

    # 3. Kontext aufbauen
    context = "Relevante Ninox-Scripts:\n\n"
    for script in relevant_scripts:
        context += f"""
---
Pfad: {script[1]}
Typ: {script[2]}
Ähnlichkeit: {script[4]:.2f}

```ninox
{script[3]}
```
"""

    # 4. LLM mit Kontext befragen
    response = llm_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="""Du bist ein Ninox-Experte. Beantworte Fragen basierend auf
                  den bereitgestellten Scripts. Wenn du Code zitierst,
                  nenne immer den Pfad.""",
        messages=[
            {"role": "user", "content": f"{context}\n\nFrage: {user_question}"}
        ]
    )

    return response.content[0].text
```

### 2.4 Option C: Hybrid-Ansatz (Empfohlen)

Der Hybrid-Ansatz kombiniert Function Calling mit semantischer Suche:

#### 2.4.1 Erweiterte Tool-Definition

```json
{
  "name": "search_ninox_scripts",
  "description": "Durchsucht Ninox-Scripts mit Keyword- und semantischer Suche.",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Suchanfrage"
      },
      "search_mode": {
        "type": "string",
        "enum": ["keyword", "semantic", "hybrid"],
        "default": "hybrid",
        "description": "keyword=exakte Suche, semantic=ähnliche Konzepte, hybrid=beides"
      }
    },
    "required": ["query"]
  }
}
```

#### 2.4.2 Hybrid-Suche Implementierung

```python
def hybrid_search(query: str, db_conn, embedding_client, mode: str = "hybrid") -> dict:
    """
    Kombiniert Keyword- und semantische Suche.
    """
    results = {"keyword": [], "semantic": [], "merged": []}

    # Keyword-Suche (FTS + Trigram)
    if mode in ["keyword", "hybrid"]:
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT id, table_name, element_name, code_type, code,
                       ts_rank(search_vector, query) AS rank
                FROM ninox_scripts, plainto_tsquery('simple', %s) query
                WHERE search_vector @@ query
                ORDER BY rank DESC
                LIMIT 10
            """, (query,))
            results["keyword"] = cur.fetchall()

    # Semantische Suche
    if mode in ["semantic", "hybrid"]:
        query_embedding = embedding_client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        ).data[0].embedding

        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT id, table_name, element_name, code_type, code,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM ninox_scripts
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """, (query_embedding, query_embedding))
            results["semantic"] = cur.fetchall()

    # Ergebnisse mergen (Reciprocal Rank Fusion)
    if mode == "hybrid":
        results["merged"] = reciprocal_rank_fusion(
            results["keyword"],
            results["semantic"]
        )

    return results


def reciprocal_rank_fusion(keyword_results, semantic_results, k=60) -> list:
    """
    Kombiniert zwei Ranglisten mit Reciprocal Rank Fusion.
    """
    scores = {}

    for rank, result in enumerate(keyword_results):
        doc_id = result[0]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)

    for rank, result in enumerate(semantic_results):
        doc_id = result[0]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)

    # Nach Score sortieren
    all_results = {r[0]: r for r in keyword_results + semantic_results}
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    return [all_results[doc_id] for doc_id in sorted_ids if doc_id in all_results]
```

### 2.5 MCP Server (Model Context Protocol)

Für die Integration mit Claude Desktop oder anderen MCP-fähigen Clients:

#### 2.5.1 MCP Server Struktur

```python
# mcp_server.py
from mcp import Server, Tool, Resource

server = Server("ninox-scripts")

@server.tool()
async def search_scripts(query: str, code_type: str = None) -> str:
    """Durchsucht Ninox-Scripts."""
    # ... Implementierung wie oben
    pass

@server.tool()
async def get_table_info(table_name: str) -> str:
    """Zeigt Tabelleninformationen."""
    pass

@server.resource("ninox://scripts/{script_id}")
async def get_script(script_id: int) -> str:
    """Lädt ein einzelnes Script."""
    pass

@server.resource("ninox://tables")
async def list_all_tables() -> str:
    """Listet alle Tabellen."""
    pass

if __name__ == "__main__":
    server.run()
```

#### 2.5.2 MCP Konfiguration (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "ninox": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost/ninox",
        "REDIS_URL": "redis://localhost:6379"
      }
    }
  }
}
```

---

## Teil 3: Migrations-Checkliste

### 3.1 Schritt-für-Schritt Migration

```
□ 1. PostgreSQL Setup
    □ Extensions installieren (pg_trgm, vector)
    □ Tabellen erstellen
    □ Trigger erstellen
    □ Views erstellen

□ 2. Redis Setup
    □ Key-Prefix festlegen (ninox:)
    □ TTL-Werte konfigurieren
    □ Invalidierungs-Logik implementieren

□ 3. Code-Anpassungen
    □ Storage-Abstraktion implementieren
    □ PostgreSQL-Backend implementieren
    □ Redis-Caching implementieren
    □ Bestehende SQLite-Daten migrieren

□ 4. API-Endpunkte
    □ Search-Endpoint implementieren
    □ CRUD-Endpoints implementieren
    □ Rate-Limiting konfigurieren

□ 5. KI-Integration
    □ Tool-Definitionen erstellen
    □ Tool-Handler implementieren
    □ (Optional) Embeddings generieren
    □ (Optional) MCP Server aufsetzen

□ 6. Testing
    □ Such-Performance testen
    □ Cache-Invalidierung testen
    □ Tool-Calls testen
```

### 3.2 Performance-Ziele

| Metrik | Ziel |
|--------|------|
| Keyword-Suche | < 50ms |
| Semantische Suche | < 200ms |
| Cache-Hit | < 10ms |
| Extraktion (1000 Scripts) | < 30s |

---

## Anhang A: Ninox Code-Typen Referenz

| code_type | code_category | Beschreibung |
|-----------|---------------|--------------|
| `globalCode` | GLOBAL_FUNCTION | Globaler Datenbankcode |
| `afterCreate` | TRIGGER | Nach Datensatz-Erstellung |
| `afterUpdate` | TRIGGER | Nach Datensatz-Änderung |
| `beforeDelete` | TRIGGER | Vor Datensatz-Löschung |
| `fn` | FORMULA | Formelfeld-Berechnung |
| `onClick` | BUTTON | Button-Klick-Handler |
| `canRead` | PERMISSION | Lese-Berechtigung |
| `canWrite` | PERMISSION | Schreib-Berechtigung |
| `canCreate` | PERMISSION | Erstell-Berechtigung |
| `canDelete` | PERMISSION | Lösch-Berechtigung |
| `validation` | FORMULA | Validierungsformel |
| `constraint` | FORMULA | Constraint-Formel |
| `dchoiceValues` | FORMULA | Dynamische Auswahl-Werte |
| `dchoiceCaption` | FORMULA | Dynamische Auswahl-Beschriftung |

---

## Anhang B: SQLite-Schema (Aktueller Stand)

Das aktuelle SQLite-Schema im Ninox API Extractor enthält folgende Tabellen:

```sql
-- script_dependencies (Cross-Database-Referenzen)
CREATE TABLE script_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL,
    source_database_id TEXT NOT NULL,
    source_database_name TEXT,
    target_database_name TEXT NOT NULL,
    reference_type TEXT NOT NULL,  -- 'do as database', 'do as server', 'openDatabase'
    code_snippet TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
);

-- Indizes
CREATE INDEX idx_dependencies_script ON script_dependencies(script_id);
CREATE INDEX idx_dependencies_source ON script_dependencies(source_database_name);
CREATE INDEX idx_dependencies_target ON script_dependencies(target_database_name);
```

**Beispiel-Abfragen:**

```sql
-- Dependency-Matrix
SELECT source_database_name AS Von,
       target_database_name AS Nach,
       reference_type AS Typ,
       COUNT(*) AS Anzahl
FROM script_dependencies
GROUP BY Von, Nach, Typ
ORDER BY Anzahl DESC;

-- Dependencies mit Script-Kontext
SELECT d.source_database_name, d.target_database_name,
       s.table_name, s.element_name, d.code_snippet
FROM script_dependencies d
JOIN scripts s ON d.script_id = s.id
WHERE d.target_database_name = '02 - Mitarbeiter';
```

---

*Erstellt: 2026-01-16*
*Aktualisiert: 2026-01-16*
*Version: 1.1*
