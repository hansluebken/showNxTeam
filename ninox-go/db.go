package main

import (
	"database/sql"
	"fmt"

	_ "github.com/mattn/go-sqlite3"
)

// Database repräsentiert eine Ninox-Datenbank
type Database struct {
	ID         string
	Name       string
	TableCount int
	CodeCount  int
}

// Table repräsentiert eine Ninox-Tabelle
type Table struct {
	ID         int
	DatabaseID string
	TableID    string
	Name       string
	Caption    string
	FieldCount int
}

// Field repräsentiert ein Ninox-Feld
type Field struct {
	ID           int
	DatabaseID   string
	TableID      string
	FieldID      string
	Name         string
	Caption      string
	BaseType     string
	RefTableName string
	HasFormula   bool
}

// Script repräsentiert ein Ninox-Script
type Script struct {
	ID           int
	DatabaseID   string
	DatabaseName string
	TableID      string
	TableName    string
	ElementID    string
	ElementName  string
	CodeType     string
	CodeCategory string
	Code         string
	LineCount    int
}

// Relationship repräsentiert eine Tabellenbeziehung
type Relationship struct {
	ID               int
	DatabaseName     string
	SourceTableName  string
	SourceFieldName  string
	TargetTableName  string
	RelationshipType string
	IsComposition    bool
}

// Stats enthält Statistiken
type Stats struct {
	DatabasesCount     int
	TablesCount        int
	FieldsCount        int
	RelationshipsCount int
	ScriptsCount       int
	ScriptsByType      map[string]int
	TopTables          map[string]int
}

// NinoxDB ist der Datenbank-Handler
type NinoxDB struct {
	conn *sql.DB
	path string
}

// NewNinoxDB öffnet eine Ninox-SQLite-Datenbank
func NewNinoxDB(path string) (*NinoxDB, error) {
	conn, err := sql.Open("sqlite3", path)
	if err != nil {
		return nil, fmt.Errorf("Fehler beim Öffnen der DB: %w", err)
	}

	// Verbindung testen
	if err := conn.Ping(); err != nil {
		return nil, fmt.Errorf("DB nicht erreichbar: %w", err)
	}

	return &NinoxDB{conn: conn, path: path}, nil
}

// Close schließt die Datenbankverbindung
func (db *NinoxDB) Close() error {
	if db.conn != nil {
		return db.conn.Close()
	}
	return nil
}

// GetDatabases lädt alle Datenbanken
func (db *NinoxDB) GetDatabases() ([]Database, error) {
	rows, err := db.conn.Query(`
		SELECT id, name, table_count, code_count
		FROM databases
		ORDER BY name
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var databases []Database
	for rows.Next() {
		var d Database
		if err := rows.Scan(&d.ID, &d.Name, &d.TableCount, &d.CodeCount); err != nil {
			return nil, err
		}
		databases = append(databases, d)
	}
	return databases, nil
}

// GetTables lädt Tabellen einer Datenbank
func (db *NinoxDB) GetTables(databaseID string) ([]Table, error) {
	rows, err := db.conn.Query(`
		SELECT id, database_id, table_id, name, caption, field_count
		FROM tables
		WHERE database_id = ?
		ORDER BY name
	`, databaseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var tables []Table
	for rows.Next() {
		var t Table
		var caption sql.NullString
		if err := rows.Scan(&t.ID, &t.DatabaseID, &t.TableID, &t.Name, &caption, &t.FieldCount); err != nil {
			return nil, err
		}
		t.Caption = caption.String
		tables = append(tables, t)
	}
	return tables, nil
}

// GetFields lädt Felder einer Tabelle
func (db *NinoxDB) GetFields(databaseID, tableID string) ([]Field, error) {
	rows, err := db.conn.Query(`
		SELECT id, database_id, table_id, field_id, name, caption,
		       base_type, ref_table_name, has_formula
		FROM fields
		WHERE database_id = ? AND table_id = ?
		ORDER BY name
	`, databaseID, tableID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var fields []Field
	for rows.Next() {
		var f Field
		var caption, baseType, refTable sql.NullString
		var hasFormula int
		if err := rows.Scan(&f.ID, &f.DatabaseID, &f.TableID, &f.FieldID,
			&f.Name, &caption, &baseType, &refTable, &hasFormula); err != nil {
			return nil, err
		}
		f.Caption = caption.String
		f.BaseType = baseType.String
		f.RefTableName = refTable.String
		f.HasFormula = hasFormula == 1
		fields = append(fields, f)
	}
	return fields, nil
}

// GetScripts lädt Scripts einer Tabelle
func (db *NinoxDB) GetScripts(databaseID, tableName string) ([]Script, error) {
	rows, err := db.conn.Query(`
		SELECT id, database_id, database_name, table_id, table_name,
		       element_id, element_name, code_type, code_category, code, line_count
		FROM scripts
		WHERE database_id = ? AND table_name = ?
		ORDER BY code_type, element_name
	`, databaseID, tableName)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var scripts []Script
	for rows.Next() {
		var s Script
		var tableID, tableName, elementID, elementName, codeCategory sql.NullString
		if err := rows.Scan(&s.ID, &s.DatabaseID, &s.DatabaseName, &tableID, &tableName,
			&elementID, &elementName, &s.CodeType, &codeCategory, &s.Code, &s.LineCount); err != nil {
			return nil, err
		}
		s.TableID = tableID.String
		s.TableName = tableName.String
		s.ElementID = elementID.String
		s.ElementName = elementName.String
		s.CodeCategory = codeCategory.String
		scripts = append(scripts, s)
	}
	return scripts, nil
}

// GetAllScripts lädt alle Scripts
func (db *NinoxDB) GetAllScripts() ([]Script, error) {
	rows, err := db.conn.Query(`
		SELECT id, database_id, database_name, table_id, table_name,
		       element_id, element_name, code_type, code_category, code, line_count
		FROM scripts
		ORDER BY database_name, table_name, code_type
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var scripts []Script
	for rows.Next() {
		var s Script
		var tableID, tableName, elementID, elementName, codeCategory sql.NullString
		if err := rows.Scan(&s.ID, &s.DatabaseID, &s.DatabaseName, &tableID, &tableName,
			&elementID, &elementName, &s.CodeType, &codeCategory, &s.Code, &s.LineCount); err != nil {
			return nil, err
		}
		s.TableID = tableID.String
		s.TableName = tableName.String
		s.ElementID = elementID.String
		s.ElementName = elementName.String
		s.CodeCategory = codeCategory.String
		scripts = append(scripts, s)
	}
	return scripts, nil
}

// SearchScripts sucht in Scripts
func (db *NinoxDB) SearchScripts(query string, limit int) ([]Script, error) {
	// Erst FTS5 versuchen
	rows, err := db.conn.Query(`
		SELECT s.id, s.database_id, s.database_name, s.table_id, s.table_name,
		       s.element_id, s.element_name, s.code_type, s.code_category, s.code, s.line_count
		FROM scripts_fts
		JOIN scripts s ON scripts_fts.rowid = s.id
		WHERE scripts_fts MATCH ?
		ORDER BY rank
		LIMIT ?
	`, query, limit)

	if err != nil {
		// Fallback auf LIKE
		rows, err = db.conn.Query(`
			SELECT id, database_id, database_name, table_id, table_name,
			       element_id, element_name, code_type, code_category, code, line_count
			FROM scripts
			WHERE code LIKE ? OR table_name LIKE ? OR element_name LIKE ?
			ORDER BY database_name, table_name
			LIMIT ?
		`, "%"+query+"%", "%"+query+"%", "%"+query+"%", limit)
		if err != nil {
			return nil, err
		}
	}
	defer rows.Close()

	var scripts []Script
	for rows.Next() {
		var s Script
		var tableID, tableName, elementID, elementName, codeCategory sql.NullString
		if err := rows.Scan(&s.ID, &s.DatabaseID, &s.DatabaseName, &tableID, &tableName,
			&elementID, &elementName, &s.CodeType, &codeCategory, &s.Code, &s.LineCount); err != nil {
			return nil, err
		}
		s.TableID = tableID.String
		s.TableName = tableName.String
		s.ElementID = elementID.String
		s.ElementName = elementName.String
		s.CodeCategory = codeCategory.String
		scripts = append(scripts, s)
	}
	return scripts, nil
}

// GetRelationships lädt Beziehungen für eine Tabelle
func (db *NinoxDB) GetRelationships(tableName string) ([]Relationship, error) {
	rows, err := db.conn.Query(`
		SELECT id, database_name, source_table_name, source_field_name,
		       target_table_name, relationship_type, is_composition
		FROM relationships
		WHERE source_table_name = ? OR target_table_name = ?
		ORDER BY source_table_name, target_table_name
	`, tableName, tableName)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var rels []Relationship
	for rows.Next() {
		var r Relationship
		var dbName, srcField sql.NullString
		var isComp int
		if err := rows.Scan(&r.ID, &dbName, &r.SourceTableName, &srcField,
			&r.TargetTableName, &r.RelationshipType, &isComp); err != nil {
			return nil, err
		}
		r.DatabaseName = dbName.String
		r.SourceFieldName = srcField.String
		r.IsComposition = isComp == 1
		rels = append(rels, r)
	}
	return rels, nil
}

// GetStats lädt Statistiken
func (db *NinoxDB) GetStats() (*Stats, error) {
	stats := &Stats{
		ScriptsByType: make(map[string]int),
		TopTables:     make(map[string]int),
	}

	// Counts
	tables := []struct {
		name  string
		count *int
	}{
		{"databases", &stats.DatabasesCount},
		{"tables", &stats.TablesCount},
		{"fields", &stats.FieldsCount},
		{"relationships", &stats.RelationshipsCount},
		{"scripts", &stats.ScriptsCount},
	}

	for _, t := range tables {
		row := db.conn.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s", t.name))
		if err := row.Scan(t.count); err != nil {
			return nil, err
		}
	}

	// Scripts by type
	rows, err := db.conn.Query(`
		SELECT code_type, COUNT(*) as count
		FROM scripts
		GROUP BY code_type
		ORDER BY count DESC
	`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var codeType string
			var count int
			if err := rows.Scan(&codeType, &count); err == nil {
				stats.ScriptsByType[codeType] = count
			}
		}
	}

	// Top tables
	rows, err = db.conn.Query(`
		SELECT table_name, COUNT(*) as count
		FROM scripts
		WHERE table_name IS NOT NULL AND table_name != ''
		GROUP BY table_name
		ORDER BY count DESC
		LIMIT 10
	`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var tableName string
			var count int
			if err := rows.Scan(&tableName, &count); err == nil {
				stats.TopTables[tableName] = count
			}
		}
	}

	return stats, nil
}
