package main

import (
	"bytes"
	"fmt"
	"os"
	"strings"

	"github.com/alecthomas/chroma/v2"
	"github.com/alecthomas/chroma/v2/formatters"
	"github.com/alecthomas/chroma/v2/lexers"
	"github.com/alecthomas/chroma/v2/styles"
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// =============================================================================
// Farbprofile / Themes
// =============================================================================

// Theme definiert ein Farbschema
type Theme struct {
	Name            string
	Primary         lipgloss.Color
	Secondary       lipgloss.Color
	Accent          lipgloss.Color
	Text            lipgloss.Color
	TextMuted       lipgloss.Color
	Background      lipgloss.Color
	Surface         lipgloss.Color
	Border          lipgloss.Color
	SelectionFg     lipgloss.Color
	SelectionBg     lipgloss.Color
	CodeStyle       string // Chroma style name
}

// Dunkles Theme - für dunkle Terminal-Hintergründe
var DarkTheme = Theme{
	Name:            "dark",
	Primary:         lipgloss.Color("#00BFFF"), // Hellblau
	Secondary:       lipgloss.Color("#00FF7F"), // Frühlingsgrün
	Accent:          lipgloss.Color("#FFD700"), // Gold
	Text:            lipgloss.Color("#FFFFFF"), // Weiß
	TextMuted:       lipgloss.Color("#888888"), // Grau
	Background:      lipgloss.Color("#000000"), // Schwarz
	Surface:         lipgloss.Color("#1C1C1C"), // Dunkelgrau
	Border:          lipgloss.Color("#444444"), // Mittelgrau
	SelectionFg:     lipgloss.Color("#000000"), // Schwarz
	SelectionBg:     lipgloss.Color("#00BFFF"), // Hellblau
	CodeStyle:       "monokai",
}

// Helles Theme - für helle Terminal-Hintergründe
var LightTheme = Theme{
	Name:            "light",
	Primary:         lipgloss.Color("#0066CC"), // Dunkelblau
	Secondary:       lipgloss.Color("#008800"), // Dunkelgrün
	Accent:          lipgloss.Color("#CC6600"), // Orange
	Text:            lipgloss.Color("#000000"), // Schwarz
	TextMuted:       lipgloss.Color("#666666"), // Dunkelgrau
	Background:      lipgloss.Color("#FFFFFF"), // Weiß
	Surface:         lipgloss.Color("#F0F0F0"), // Hellgrau
	Border:          lipgloss.Color("#CCCCCC"), // Hellgrau
	SelectionFg:     lipgloss.Color("#FFFFFF"), // Weiß
	SelectionBg:     lipgloss.Color("#0066CC"), // Dunkelblau
	CodeStyle:       "github",
}

// Aktuelles Theme (wird beim Start gesetzt)
var currentTheme = DarkTheme

// Styles - werden dynamisch basierend auf Theme gesetzt
var (
	titleStyle             lipgloss.Style
	headerStyle            lipgloss.Style
	selectedStyle          lipgloss.Style
	normalStyle            lipgloss.Style
	mutedStyle             lipgloss.Style
	boxStyle               lipgloss.Style
	codeBoxStyle           lipgloss.Style
	statsBoxStyle          lipgloss.Style
	helpStyle              lipgloss.Style
	tableHeaderStyle       lipgloss.Style
	tableCellStyle         lipgloss.Style
	tableCellSelectedStyle lipgloss.Style
)

// applyTheme wendet ein Theme auf alle Styles an
func applyTheme(theme Theme) {
	currentTheme = theme

	titleStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.Primary).
		Padding(0, 1)

	headerStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.Primary).
		Padding(0, 1).
		MarginBottom(1)

	selectedStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.SelectionBg)

	normalStyle = lipgloss.NewStyle().
		Foreground(theme.Text)

	mutedStyle = lipgloss.NewStyle().
		Foreground(theme.TextMuted)

	boxStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(theme.Border).
		Padding(1)

	codeBoxStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(theme.Secondary).
		Padding(0, 1)

	statsBoxStyle = lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(theme.Accent).
		Padding(0, 1)

	helpStyle = lipgloss.NewStyle().
		Foreground(theme.TextMuted).
		Padding(0, 1)

	tableHeaderStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.Primary).
		BorderBottom(true).
		BorderStyle(lipgloss.NormalBorder()).
		BorderForeground(theme.Border)

	tableCellStyle = lipgloss.NewStyle().
		Foreground(theme.Text).
		Padding(0, 1)

	tableCellSelectedStyle = lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.SelectionBg).
		Padding(0, 1)
}

func init() {
	// Standard-Theme beim Start anwenden
	applyTheme(DarkTheme)
}

// View-Modi
type viewMode int

const (
	viewDatabases viewMode = iota
	viewTables
	viewFields
	viewScripts
	viewCode
	viewSearch
	viewStats
	viewHelp
	viewAllScripts // Neue Gesamtansicht aller Scripts
)

// Tastenbelegung
type keyMap struct {
	Up        key.Binding
	Down      key.Binding
	Left      key.Binding
	Right     key.Binding
	Enter     key.Binding
	Back      key.Binding
	Search    key.Binding
	Stats     key.Binding
	Help      key.Binding
	Tab       key.Binding
	Quit      key.Binding
	PageUp    key.Binding
	PageDown  key.Binding
	AllScripts key.Binding // Neue Taste für Gesamtansicht
	Filter    key.Binding  // Filter aktivieren
}

var keys = keyMap{
	Up:        key.NewBinding(key.WithKeys("up", "k"), key.WithHelp("↑/k", "hoch")),
	Down:      key.NewBinding(key.WithKeys("down", "j"), key.WithHelp("↓/j", "runter")),
	Left:      key.NewBinding(key.WithKeys("left", "h"), key.WithHelp("←/h", "zurück")),
	Right:     key.NewBinding(key.WithKeys("right", "l"), key.WithHelp("→/l", "öffnen")),
	Enter:     key.NewBinding(key.WithKeys("enter"), key.WithHelp("Enter", "auswählen")),
	Back:      key.NewBinding(key.WithKeys("esc", "backspace"), key.WithHelp("Esc", "zurück")),
	Search:    key.NewBinding(key.WithKeys("s", "/"), key.WithHelp("s", "suchen")),
	Stats:     key.NewBinding(key.WithKeys("i"), key.WithHelp("i", "info")),
	Help:      key.NewBinding(key.WithKeys("?"), key.WithHelp("?", "hilfe")),
	Tab:       key.NewBinding(key.WithKeys("tab"), key.WithHelp("Tab", "wechseln")),
	Quit:      key.NewBinding(key.WithKeys("q", "ctrl+c"), key.WithHelp("q", "beenden")),
	PageUp:    key.NewBinding(key.WithKeys("pgup", "ctrl+u"), key.WithHelp("PgUp", "seite hoch")),
	PageDown:  key.NewBinding(key.WithKeys("pgdown", "ctrl+d"), key.WithHelp("PgDn", "seite runter")),
	AllScripts: key.NewBinding(key.WithKeys("a"), key.WithHelp("a", "alle Scripts")),
	Filter:    key.NewBinding(key.WithKeys("f"), key.WithHelp("f", "filter")),
}

// Model ist das Hauptmodell der Anwendung
type Model struct {
	db            *NinoxDB
	width, height int
	mode          viewMode
	prevMode      viewMode

	// Daten
	databases     []Database
	tables        []Table
	fields        []Field
	scripts       []Script
	searchResults []Script
	relationships []Relationship
	stats         *Stats

	// Gesamtansicht aller Scripts
	allScripts         []Script // Alle Scripts aus der DB
	filteredScripts    []Script // Gefilterte Scripts
	selectedAllScript  int      // Auswahl in der Gesamtliste
	filterInput        textinput.Model // Filter-Eingabe
	filterText         string   // Aktueller Filter-Text
	filtering          bool     // Filter-Modus aktiv
	scrollOffset       int      // Scroll-Position in der Liste

	// Auswahl
	selectedDB     int
	selectedTable  int
	selectedField  int
	selectedScript int
	selectedSearch int

	// UI-Komponenten
	searchInput textinput.Model
	codeView    viewport.Model
	listView    viewport.Model

	// Aktueller Kontext
	currentDB    *Database
	currentTable *Table

	// Flags
	searching bool
	err       error
}

// NewModel erstellt ein neues Model
func NewModel(dbPath string) (*Model, error) {
	db, err := NewNinoxDB(dbPath)
	if err != nil {
		return nil, err
	}

	// Datenbanken laden
	databases, err := db.GetDatabases()
	if err != nil {
		return nil, err
	}

	// Statistiken laden
	stats, err := db.GetStats()
	if err != nil {
		stats = &Stats{}
	}

	// Alle Scripts laden für Gesamtansicht
	allScripts, err := db.GetAllScripts()
	if err != nil {
		allScripts = []Script{}
	}

	// Sucheingabe
	ti := textinput.New()
	ti.Placeholder = "Suchbegriff eingeben..."
	ti.CharLimit = 100
	ti.Width = 50

	// Filter-Eingabe
	fi := textinput.New()
	fi.Placeholder = "Filter: Begriff AND Begriff OR Begriff..."
	fi.CharLimit = 200
	fi.Width = 80

	// Viewports
	cv := viewport.New(80, 20)
	lv := viewport.New(80, 20)

	return &Model{
		db:              db,
		databases:       databases,
		stats:           stats,
		mode:            viewDatabases,
		searchInput:     ti,
		filterInput:     fi,
		codeView:        cv,
		listView:        lv,
		allScripts:      allScripts,
		filteredScripts: allScripts, // Initial alle anzeigen
	}, nil
}

// Init initialisiert das Model
func (m Model) Init() tea.Cmd {
	return nil
}

// Update verarbeitet Nachrichten
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.codeView.Width = msg.Width - 4
		m.codeView.Height = msg.Height - 10
		m.listView.Width = msg.Width - 4
		m.listView.Height = msg.Height - 8
		return m, nil

	case tea.KeyMsg:
		// Im Such-Modus
		if m.searching {
			switch {
			case key.Matches(msg, keys.Back):
				m.searching = false
				m.searchInput.Blur()
				return m, nil
			case key.Matches(msg, keys.Enter):
				m.searching = false
				m.searchInput.Blur()
				results, err := m.db.SearchScripts(m.searchInput.Value(), 50)
				if err == nil {
					m.searchResults = results
					m.selectedSearch = 0
					m.mode = viewSearch
				}
				return m, nil
			default:
				m.searchInput, cmd = m.searchInput.Update(msg)
				return m, cmd
			}
		}

		// Im Filter-Modus
		if m.filtering {
			switch {
			case key.Matches(msg, keys.Back):
				m.filtering = false
				m.filterInput.Blur()
				return m, nil
			case key.Matches(msg, keys.Enter):
				m.filtering = false
				m.filterInput.Blur()
				m.filterText = m.filterInput.Value()
				m.applyFilter()
				return m, nil
			default:
				m.filterInput, cmd = m.filterInput.Update(msg)
				return m, cmd
			}
		}

		// Normale Navigation
		switch {
		case key.Matches(msg, keys.Quit):
			return m, tea.Quit

		case key.Matches(msg, keys.Search):
			m.searching = true
			m.searchInput.Focus()
			return m, textinput.Blink

		case key.Matches(msg, keys.AllScripts):
			m.prevMode = m.mode
			m.mode = viewAllScripts
			m.selectedAllScript = 0
			m.scrollOffset = 0
			return m, nil

		case key.Matches(msg, keys.Filter):
			if m.mode == viewAllScripts {
				m.filtering = true
				m.filterInput.Focus()
				return m, textinput.Blink
			}
			return m, nil

		case key.Matches(msg, keys.Stats):
			if m.mode == viewStats {
				m.mode = m.prevMode
			} else {
				m.prevMode = m.mode
				m.mode = viewStats
			}
			return m, nil

		case key.Matches(msg, keys.Help):
			if m.mode == viewHelp {
				m.mode = m.prevMode
			} else {
				m.prevMode = m.mode
				m.mode = viewHelp
			}
			return m, nil

		case key.Matches(msg, keys.Back):
			return m.handleBack()

		case key.Matches(msg, keys.Up):
			return m.handleUp()

		case key.Matches(msg, keys.Down):
			return m.handleDown()

		case key.Matches(msg, keys.Enter), key.Matches(msg, keys.Right):
			return m.handleEnter()

		case key.Matches(msg, keys.Tab):
			return m.handleTab()

		case key.Matches(msg, keys.PageUp):
			if m.mode == viewAllScripts {
				m.scrollOffset = max(0, m.scrollOffset-10)
			}
			m.codeView.ViewUp()
			return m, nil

		case key.Matches(msg, keys.PageDown):
			if m.mode == viewAllScripts {
				maxOffset := max(0, len(m.filteredScripts)-10)
				m.scrollOffset = min(m.scrollOffset+10, maxOffset)
			}
			m.codeView.ViewDown()
			return m, nil
		}
	}

	// Viewport updates
	m.codeView, cmd = m.codeView.Update(msg)
	cmds = append(cmds, cmd)

	return m, tea.Batch(cmds...)
}

// applyFilter wendet den Filter auf alle Scripts an
func (m *Model) applyFilter() {
	if m.filterText == "" {
		m.filteredScripts = m.allScripts
		return
	}

	m.filteredScripts = filterScripts(m.allScripts, m.filterText)
	m.selectedAllScript = 0
	m.scrollOffset = 0
}

// filterScripts filtert Scripts basierend auf AND/OR Logik
func filterScripts(scripts []Script, filter string) []Script {
	filter = strings.TrimSpace(filter)
	if filter == "" {
		return scripts
	}

	// Parse OR-Gruppen (haben niedrigere Priorität)
	orGroups := strings.Split(filter, " OR ")

	var result []Script
	for _, script := range scripts {
		if matchesFilter(script, orGroups) {
			result = append(result, script)
		}
	}
	return result
}

// matchesFilter prüft ob ein Script dem Filter entspricht
func matchesFilter(script Script, orGroups []string) bool {
	// Durchsuchbarer Text
	searchText := strings.ToLower(
		script.DatabaseName + " " +
			script.TableName + " " +
			script.ElementName + " " +
			script.CodeType + " " +
			script.CodeCategory + " " +
			script.Code,
	)

	// Mindestens eine OR-Gruppe muss matchen
	for _, orGroup := range orGroups {
		orGroup = strings.TrimSpace(orGroup)
		if orGroup == "" {
			continue
		}

		// Alle AND-Terme müssen matchen
		andTerms := strings.Split(orGroup, " AND ")
		allMatch := true

		for _, term := range andTerms {
			term = strings.TrimSpace(strings.ToLower(term))
			if term == "" {
				continue
			}
			if !strings.Contains(searchText, term) {
				allMatch = false
				break
			}
		}

		if allMatch {
			return true
		}
	}

	return false
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func (m Model) handleBack() (tea.Model, tea.Cmd) {
	switch m.mode {
	case viewTables:
		m.mode = viewDatabases
		m.currentDB = nil
	case viewFields, viewScripts:
		m.mode = viewTables
		m.currentTable = nil
	case viewCode:
		// Zurück zur vorherigen Ansicht
		if m.prevMode == viewAllScripts {
			m.mode = viewAllScripts
		} else {
			m.mode = viewScripts
		}
	case viewSearch:
		m.mode = viewDatabases
	case viewAllScripts:
		m.mode = viewDatabases
		m.filterText = ""
		m.filterInput.SetValue("")
		m.filteredScripts = m.allScripts
	case viewStats, viewHelp:
		m.mode = m.prevMode
	}
	return m, nil
}

func (m Model) handleUp() (tea.Model, tea.Cmd) {
	switch m.mode {
	case viewDatabases:
		if m.selectedDB > 0 {
			m.selectedDB--
		}
	case viewTables:
		if m.selectedTable > 0 {
			m.selectedTable--
		}
	case viewFields:
		if m.selectedField > 0 {
			m.selectedField--
		}
	case viewScripts:
		if m.selectedScript > 0 {
			m.selectedScript--
		}
	case viewSearch:
		if m.selectedSearch > 0 {
			m.selectedSearch--
		}
	case viewAllScripts:
		if m.selectedAllScript > 0 {
			m.selectedAllScript--
			// Scroll-Anpassung
			if m.selectedAllScript < m.scrollOffset {
				m.scrollOffset = m.selectedAllScript
			}
		}
	case viewCode:
		m.codeView.ViewUp()
	}
	return m, nil
}

func (m Model) handleDown() (tea.Model, tea.Cmd) {
	switch m.mode {
	case viewDatabases:
		if m.selectedDB < len(m.databases)-1 {
			m.selectedDB++
		}
	case viewTables:
		if m.selectedTable < len(m.tables)-1 {
			m.selectedTable++
		}
	case viewFields:
		if m.selectedField < len(m.fields)-1 {
			m.selectedField++
		}
	case viewScripts:
		if m.selectedScript < len(m.scripts)-1 {
			m.selectedScript++
		}
	case viewSearch:
		if m.selectedSearch < len(m.searchResults)-1 {
			m.selectedSearch++
		}
	case viewAllScripts:
		if m.selectedAllScript < len(m.filteredScripts)-1 {
			m.selectedAllScript++
			// Scroll-Anpassung (ca. 10 sichtbare Einträge)
			visibleRows := 8
			if m.selectedAllScript >= m.scrollOffset+visibleRows {
				m.scrollOffset = m.selectedAllScript - visibleRows + 1
			}
		}
	case viewCode:
		m.codeView.ViewDown()
	}
	return m, nil
}

func (m Model) handleEnter() (tea.Model, tea.Cmd) {
	switch m.mode {
	case viewDatabases:
		if len(m.databases) > 0 {
			m.currentDB = &m.databases[m.selectedDB]
			tables, err := m.db.GetTables(m.currentDB.ID)
			if err == nil {
				m.tables = tables
				m.selectedTable = 0
				m.mode = viewTables
			}
		}
	case viewTables:
		if len(m.tables) > 0 {
			m.currentTable = &m.tables[m.selectedTable]
			// Felder laden
			fields, err := m.db.GetFields(m.currentDB.ID, m.currentTable.TableID)
			if err == nil {
				m.fields = fields
				m.selectedField = 0
			}
			// Scripts laden
			scripts, err := m.db.GetScripts(m.currentDB.ID, m.currentTable.Name)
			if err == nil {
				m.scripts = scripts
				m.selectedScript = 0
			}
			// Beziehungen laden
			rels, err := m.db.GetRelationships(m.currentTable.Name)
			if err == nil {
				m.relationships = rels
			}
			m.mode = viewFields
		}
	case viewFields:
		// Zum Scripts-Tab wechseln
		m.mode = viewScripts
	case viewScripts:
		if len(m.scripts) > 0 {
			script := m.scripts[m.selectedScript]
			m.codeView.SetContent(highlightCode(script.Code))
			m.mode = viewCode
		}
	case viewSearch:
		if len(m.searchResults) > 0 {
			script := m.searchResults[m.selectedSearch]
			m.codeView.SetContent(highlightCode(script.Code))
			m.mode = viewCode
		}
	case viewAllScripts:
		if len(m.filteredScripts) > 0 && m.selectedAllScript < len(m.filteredScripts) {
			script := m.filteredScripts[m.selectedAllScript]
			m.codeView.SetContent(highlightCode(script.Code))
			m.prevMode = viewAllScripts
			m.mode = viewCode
		}
	}
	return m, nil
}

func (m Model) handleTab() (tea.Model, tea.Cmd) {
	if m.currentTable != nil {
		switch m.mode {
		case viewFields:
			m.mode = viewScripts
		case viewScripts:
			m.mode = viewFields
		}
	}
	return m, nil
}

// View rendert die Ansicht
func (m Model) View() string {
	if m.width == 0 {
		return "Lade..."
	}

	var content string

	switch m.mode {
	case viewDatabases:
		content = m.renderDatabases()
	case viewTables:
		content = m.renderTables()
	case viewFields:
		content = m.renderFields()
	case viewScripts:
		content = m.renderScripts()
	case viewCode:
		content = m.renderCode()
	case viewSearch:
		content = m.renderSearch()
	case viewStats:
		content = m.renderStats()
	case viewHelp:
		content = m.renderHelp()
	case viewAllScripts:
		content = m.renderAllScripts()
	}

	// Header
	header := m.renderHeader()

	// Suchleiste (wenn aktiv)
	searchBar := ""
	if m.searching {
		searchBar = boxStyle.Render("🔍 " + m.searchInput.View())
	}

	// Filter-Leiste (wenn aktiv)
	filterBar := ""
	if m.filtering {
		filterBar = boxStyle.Render("🔍 Filter: " + m.filterInput.View())
	} else if m.mode == viewAllScripts && m.filterText != "" {
		filterBar = mutedStyle.Render(fmt.Sprintf("  Filter: %s", m.filterText))
	}

	// Footer/Hilfe
	footer := m.renderFooter()

	// Zusammenbauen
	parts := []string{header}
	if searchBar != "" {
		parts = append(parts, searchBar)
	}
	if filterBar != "" {
		parts = append(parts, filterBar)
	}
	parts = append(parts, content, footer)

	return lipgloss.JoinVertical(lipgloss.Left, parts...)
}

func (m Model) renderHeader() string {
	title := "📦 Ninox Schema Explorer"

	// Breadcrumb
	breadcrumb := ""
	if m.currentDB != nil {
		breadcrumb = m.currentDB.Name
		if m.currentTable != nil {
			breadcrumb += " > " + m.currentTable.Name
		}
	}

	left := headerStyle.Render(title)
	right := mutedStyle.Render(breadcrumb)

	gap := m.width - lipgloss.Width(left) - lipgloss.Width(right) - 2
	if gap < 0 {
		gap = 0
	}

	return left + strings.Repeat(" ", gap) + right
}

func (m Model) renderFooter() string {
	help := "↑↓ Navigation • Enter Auswählen • Esc Zurück • a Alle Scripts • s Suchen • i Info • ? Hilfe • q Beenden"
	if m.mode == viewFields || m.mode == viewScripts {
		help = "Tab Wechseln • " + help
	}
	if m.mode == viewAllScripts {
		help = "↑↓ Navigation • Enter Code • f Filter • Esc Zurück • ? Hilfe • q Beenden"
	}
	return helpStyle.Render(help)
}

func (m Model) renderDatabases() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("📁 Datenbanken") + "\n\n")

	// Tabellen-Header
	header := fmt.Sprintf("  %-30s %10s %10s", "Name", "Tabellen", "Scripts")
	b.WriteString(tableHeaderStyle.Render(header) + "\n")

	for i, db := range m.databases {
		style := tableCellStyle
		prefix := "  "
		if i == m.selectedDB {
			style = tableCellSelectedStyle
			prefix = "▶ "
		}

		row := fmt.Sprintf("%s%-28s %10d %10d",
			prefix, truncate(db.Name, 28), db.TableCount, db.CodeCount)
		b.WriteString(style.Render(row) + "\n")
	}

	return boxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderTables() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("📋 Tabellen: "+m.currentDB.Name) + "\n\n")

	header := fmt.Sprintf("  %-35s %10s", "Name", "Felder")
	b.WriteString(tableHeaderStyle.Render(header) + "\n")

	for i, t := range m.tables {
		style := tableCellStyle
		prefix := "  "
		if i == m.selectedTable {
			style = tableCellSelectedStyle
			prefix = "▶ "
		}

		row := fmt.Sprintf("%s%-33s %10d", prefix, truncate(t.Name, 33), t.FieldCount)
		b.WriteString(style.Render(row) + "\n")
	}

	return boxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderFields() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("🔤 Felder: "+m.currentTable.Name) + "\n\n")

	header := fmt.Sprintf("  %-25s %-10s %-12s %-20s %s",
		"Name", "ID", "Typ", "Referenz", "Formel")
	b.WriteString(tableHeaderStyle.Render(header) + "\n")

	for i, f := range m.fields {
		style := tableCellStyle
		prefix := "  "
		if i == m.selectedField {
			style = tableCellSelectedStyle
			prefix = "▶ "
		}

		formula := ""
		if f.HasFormula {
			formula = "✓"
		}

		name := f.Caption
		if name == "" {
			name = f.Name
		}

		row := fmt.Sprintf("%s%-23s %-10s %-12s %-20s %s",
			prefix,
			truncate(name, 23),
			truncate(f.FieldID, 10),
			truncate(f.BaseType, 12),
			truncate(f.RefTableName, 20),
			formula)
		b.WriteString(style.Render(row) + "\n")
	}

	// Beziehungen anzeigen
	if len(m.relationships) > 0 {
		b.WriteString("\n" + titleStyle.Render("🔗 Beziehungen") + "\n\n")
		for _, r := range m.relationships {
			direction := "→"
			other := r.TargetTableName
			if r.TargetTableName == m.currentTable.Name {
				direction = "←"
				other = r.SourceTableName
			}
			line := fmt.Sprintf("  %s %s (%s)", direction, other, r.RelationshipType)
			b.WriteString(mutedStyle.Render(line) + "\n")
		}
	}

	return boxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderScripts() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("📜 Scripts: "+m.currentTable.Name) + "\n\n")

	if len(m.scripts) == 0 {
		b.WriteString(mutedStyle.Render("  Keine Scripts vorhanden\n"))
	} else {
		header := fmt.Sprintf("  %-25s %-15s %-12s %s",
			"Element", "Typ", "Kategorie", "Zeilen")
		b.WriteString(tableHeaderStyle.Render(header) + "\n")

		for i, s := range m.scripts {
			style := tableCellStyle
			prefix := "  "
			if i == m.selectedScript {
				style = tableCellSelectedStyle
				prefix = "▶ "
			}

			element := s.ElementName
			if element == "" {
				element = "(Tabelle)"
			}

			row := fmt.Sprintf("%s%-23s %-15s %-12s %5d",
				prefix,
				truncate(element, 23),
				truncate(s.CodeType, 15),
				truncate(s.CodeCategory, 12),
				s.LineCount)
			b.WriteString(style.Render(row) + "\n")
		}
	}

	return boxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderCode() string {
	var b strings.Builder

	title := "Code"
	if len(m.scripts) > 0 && m.selectedScript < len(m.scripts) {
		s := m.scripts[m.selectedScript]
		title = fmt.Sprintf("%s - %s", s.ElementName, s.CodeType)
		if s.ElementName == "" {
			title = fmt.Sprintf("(Tabelle) - %s", s.CodeType)
		}
	}

	b.WriteString(titleStyle.Render("💻 "+title) + "\n\n")
	b.WriteString(m.codeView.View())

	scrollInfo := fmt.Sprintf(" %d%% ", int(m.codeView.ScrollPercent()*100))
	b.WriteString("\n" + mutedStyle.Render(scrollInfo))

	return codeBoxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderSearch() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render(fmt.Sprintf("🔍 Suchergebnisse: \"%s\"", m.searchInput.Value())) + "\n\n")

	if len(m.searchResults) == 0 {
		b.WriteString(mutedStyle.Render("  Keine Treffer gefunden\n"))
	} else {
		b.WriteString(fmt.Sprintf("  %d Treffer\n\n", len(m.searchResults)))

		header := fmt.Sprintf("  %-30s %-20s %-12s %s",
			"Datenbank.Tabelle", "Element", "Typ", "Zeilen")
		b.WriteString(tableHeaderStyle.Render(header) + "\n")

		for i, s := range m.searchResults {
			style := tableCellStyle
			prefix := "  "
			if i == m.selectedSearch {
				style = tableCellSelectedStyle
				prefix = "▶ "
			}

			loc := s.DatabaseName
			if s.TableName != "" {
				loc += "." + s.TableName
			}

			element := s.ElementName
			if element == "" {
				element = "(Tabelle)"
			}

			row := fmt.Sprintf("%s%-28s %-20s %-12s %5d",
				prefix,
				truncate(loc, 28),
				truncate(element, 20),
				truncate(s.CodeType, 12),
				s.LineCount)
			b.WriteString(style.Render(row) + "\n")
		}
	}

	return boxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderStats() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("📊 Statistiken") + "\n\n")

	// Hauptzahlen
	stats := []struct {
		label string
		value int
	}{
		{"Datenbanken", m.stats.DatabasesCount},
		{"Tabellen", m.stats.TablesCount},
		{"Felder", m.stats.FieldsCount},
		{"Verknüpfungen", m.stats.RelationshipsCount},
		{"Scripts", m.stats.ScriptsCount},
	}

	for _, s := range stats {
		line := fmt.Sprintf("  %-20s %8d", s.label, s.value)
		b.WriteString(normalStyle.Render(line) + "\n")
	}

	// Scripts nach Typ
	b.WriteString("\n" + titleStyle.Render("📜 Scripts nach Typ") + "\n\n")
	i := 0
	for typ, count := range m.stats.ScriptsByType {
		if i >= 8 {
			break
		}
		bar := strings.Repeat("█", min(count/5, 30))
		// Farbiger Balken mit Theme-Farbe
		barStyled := lipgloss.NewStyle().Foreground(currentTheme.Primary).Render(bar)
		b.WriteString(fmt.Sprintf("  %-15s %s %d\n", truncate(typ, 15), barStyled, count))
		i++
	}

	// Top Tabellen
	b.WriteString("\n" + titleStyle.Render("🏆 Top Tabellen") + "\n\n")
	i = 0
	for table, count := range m.stats.TopTables {
		if i >= 5 {
			break
		}
		line := fmt.Sprintf("  %d. %-25s %5d Scripts", i+1, truncate(table, 25), count)
		b.WriteString(normalStyle.Render(line) + "\n")
		i++
	}

	return statsBoxStyle.Width(m.width - 4).Render(b.String())
}

func (m Model) renderHelp() string {
	var b strings.Builder

	b.WriteString(titleStyle.Render("❓ Hilfe") + "\n\n")

	helpItems := []struct {
		key  string
		desc string
	}{
		{"↑/k, ↓/j", "Navigation hoch/runter"},
		{"Enter, →/l", "Auswählen / Öffnen"},
		{"Esc, ←/h", "Zurück"},
		{"Tab", "Zwischen Felder/Scripts wechseln"},
		{"a", "Alle Scripts (Gesamtansicht)"},
		{"f", "Filter (in Gesamtansicht)"},
		{"s, /", "Suche öffnen"},
		{"i", "Statistiken anzeigen"},
		{"?", "Diese Hilfe"},
		{"PgUp/PgDn", "Im Code scrollen"},
		{"q, Ctrl+C", "Beenden"},
	}

	for _, h := range helpItems {
		line := fmt.Sprintf("  %-15s  %s", h.key, h.desc)
		b.WriteString(normalStyle.Render(line) + "\n")
	}

	b.WriteString("\n" + titleStyle.Render("📍 Navigation") + "\n\n")
	b.WriteString(normalStyle.Render("  Datenbanken → Tabellen → Felder/Scripts → Code\n"))

	b.WriteString("\n" + titleStyle.Render("🔍 Filter-Syntax") + "\n\n")
	b.WriteString(normalStyle.Render("  Begriff AND Begriff    Beide müssen vorkommen\n"))
	b.WriteString(normalStyle.Render("  Begriff OR Begriff     Einer muss vorkommen\n"))
	b.WriteString(normalStyle.Render("  Beispiel: http AND Kunden OR email\n"))

	return boxStyle.Width(m.width - 4).Render(b.String())
}

// renderAllScripts rendert die Gesamtansicht aller Scripts
func (m Model) renderAllScripts() string {
	var b strings.Builder

	// Titel mit Statistik
	total := len(m.allScripts)
	filtered := len(m.filteredScripts)

	titleText := fmt.Sprintf("📜 Alle Scripts (%d", filtered)
	if filtered != total {
		titleText += fmt.Sprintf(" von %d", total)
	}
	titleText += ")"

	b.WriteString(titleStyle.Render(titleText) + "\n\n")

	if len(m.filteredScripts) == 0 {
		b.WriteString(mutedStyle.Render("  Keine Scripts gefunden.\n"))
		b.WriteString(mutedStyle.Render("  Drücke 'f' um den Filter zu ändern.\n"))
		return boxStyle.Width(m.width - 4).Render(b.String())
	}

	// Berechne sichtbaren Bereich
	visibleRows := m.height - 15 // Platz für Header, Footer, Code-Box
	if visibleRows < 3 {
		visibleRows = 3
	}
	visibleRows = visibleRows / 4 // Jedes Script braucht ca. 4 Zeilen

	startIdx := m.scrollOffset
	endIdx := startIdx + visibleRows
	if endIdx > len(m.filteredScripts) {
		endIdx = len(m.filteredScripts)
	}

	// Scripts anzeigen
	for i := startIdx; i < endIdx; i++ {
		s := m.filteredScripts[i]
		isSelected := i == m.selectedAllScript

		// Header-Zeile für das Script
		headerLine := fmt.Sprintf("%s │ %s │ %s │ %s │ %s",
			truncate(s.DatabaseName, 15),
			truncate(s.TableName, 15),
			truncate(s.ElementName, 15),
			truncate(s.CodeType, 12),
			truncate(s.CodeCategory, 10),
		)

		// Style basierend auf Auswahl
		headerStyle := tableCellStyle
		if isSelected {
			headerStyle = tableCellSelectedStyle
		}

		// Prefix für Auswahl
		prefix := "  "
		if isSelected {
			prefix = "▶ "
		}

		b.WriteString(headerStyle.Render(prefix+headerLine) + "\n")

		// Code-Vorschau (erste 2-3 Zeilen)
		codeLines := strings.Split(s.Code, "\n")
		previewLines := 2
		if len(codeLines) < previewLines {
			previewLines = len(codeLines)
		}

		codePreview := strings.Join(codeLines[:previewLines], "\n")
		if len(codeLines) > previewLines {
			codePreview += "\n..."
		}

		// Code-Box
		codeStyle := lipgloss.NewStyle().
			Foreground(currentTheme.TextMuted).
			Border(lipgloss.RoundedBorder()).
			BorderForeground(currentTheme.Border).
			Padding(0, 1).
			Width(m.width - 10)

		if isSelected {
			codeStyle = codeStyle.BorderForeground(currentTheme.Primary)
		}

		b.WriteString(codeStyle.Render(codePreview) + "\n\n")
	}

	// Scroll-Info
	if len(m.filteredScripts) > visibleRows {
		scrollPercent := 0
		if len(m.filteredScripts) > 0 {
			scrollPercent = (m.selectedAllScript * 100) / len(m.filteredScripts)
		}
		scrollInfo := fmt.Sprintf("  %d/%d (%d%%)", m.selectedAllScript+1, len(m.filteredScripts), scrollPercent)
		b.WriteString(mutedStyle.Render(scrollInfo))
	}

	return b.String()
}

// Hilfsfunktionen

func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen-3] + "..."
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func highlightCode(code string) string {
	// Lexer für JavaScript (Ninox ist JS-ähnlich)
	lexer := lexers.Get("javascript")
	if lexer == nil {
		lexer = lexers.Fallback
	}
	lexer = chroma.Coalesce(lexer)

	// Style basierend auf aktuellem Theme
	style := styles.Get(currentTheme.CodeStyle)
	if style == nil {
		style = styles.Fallback
	}

	// Formatter für Terminal (256 Farben)
	formatter := formatters.Get("terminal256")
	if formatter == nil {
		formatter = formatters.Fallback
	}

	// Tokenize und formatieren
	iterator, err := lexer.Tokenise(nil, code)
	if err != nil {
		return code
	}

	var buf bytes.Buffer
	err = formatter.Format(&buf, style, iterator)
	if err != nil {
		return code
	}

	// Zeilennummern hinzufügen
	lines := strings.Split(buf.String(), "\n")
	var result strings.Builder
	for i, line := range lines {
		lineNum := fmt.Sprintf("%4d │ ", i+1)
		result.WriteString(mutedStyle.Render(lineNum))
		result.WriteString(line)
		result.WriteString("\n")
	}

	return result.String()
}

func printUsage() {
	fmt.Println("Ninox Schema Explorer - Terminal UI")
	fmt.Println("")
	fmt.Println("Verwendung:")
	fmt.Println("  ninox-tui [optionen] [datenbank.db]")
	fmt.Println("")
	fmt.Println("Optionen:")
	fmt.Println("  --dark     Dunkles Farbschema (Standard)")
	fmt.Println("  --light    Helles Farbschema")
	fmt.Println("  --help     Diese Hilfe anzeigen")
	fmt.Println("")
	fmt.Println("Beispiele:")
	fmt.Println("  ninox-tui                      # Standard-DB, dunkles Theme")
	fmt.Println("  ninox-tui --light              # Standard-DB, helles Theme")
	fmt.Println("  ninox-tui --dark mydata.db     # Eigene DB, dunkles Theme")
	fmt.Println("  ninox-tui --light mydata.db    # Eigene DB, helles Theme")
}

func main() {
	dbPath := "ninox_schema.db"
	theme := DarkTheme // Standard

	// Argumente parsen
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--help", "-h":
			printUsage()
			os.Exit(0)
		case "--dark", "-d":
			theme = DarkTheme
		case "--light", "-l":
			theme = LightTheme
		default:
			if !strings.HasPrefix(arg, "-") {
				dbPath = arg
			} else {
				fmt.Printf("Unbekannte Option: %s\n", arg)
				printUsage()
				os.Exit(1)
			}
		}
	}

	// Theme anwenden
	applyTheme(theme)

	// Prüfen ob DB existiert
	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		fmt.Printf("❌ Datenbank nicht gefunden: %s\n", dbPath)
		fmt.Println("   Bitte zuerst Daten extrahieren mit dem Python-Tool.")
		os.Exit(1)
	}

	model, err := NewModel(dbPath)
	if err != nil {
		fmt.Printf("❌ Fehler: %v\n", err)
		os.Exit(1)
	}
	defer model.db.Close()

	p := tea.NewProgram(model, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Fehler: %v\n", err)
		os.Exit(1)
	}
}
