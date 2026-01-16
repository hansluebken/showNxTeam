package main

import (
	"bytes"
	"database/sql"
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
	_ "github.com/mattn/go-sqlite3"
)

// =============================================================================
// Datentypen
// =============================================================================

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

// =============================================================================
// Themes
// =============================================================================

type Theme struct {
	Name        string
	Primary     lipgloss.Color
	Secondary   lipgloss.Color
	Accent      lipgloss.Color
	Text        lipgloss.Color
	TextMuted   lipgloss.Color
	Border      lipgloss.Color
	SelectionFg lipgloss.Color
	SelectionBg lipgloss.Color
	CodeStyle   string
}

var DarkTheme = Theme{
	Name:        "dark",
	Primary:     lipgloss.Color("#00BFFF"),
	Secondary:   lipgloss.Color("#00FF7F"),
	Accent:      lipgloss.Color("#FFD700"),
	Text:        lipgloss.Color("#FFFFFF"),
	TextMuted:   lipgloss.Color("#888888"),
	Border:      lipgloss.Color("#444444"),
	SelectionFg: lipgloss.Color("#000000"),
	SelectionBg: lipgloss.Color("#00BFFF"),
	CodeStyle:   "monokai",
}

var LightTheme = Theme{
	Name:        "light",
	Primary:     lipgloss.Color("#0066CC"),
	Secondary:   lipgloss.Color("#008800"),
	Accent:      lipgloss.Color("#CC6600"),
	Text:        lipgloss.Color("#000000"),
	TextMuted:   lipgloss.Color("#666666"),
	Border:      lipgloss.Color("#CCCCCC"),
	SelectionFg: lipgloss.Color("#FFFFFF"),
	SelectionBg: lipgloss.Color("#0066CC"),
	CodeStyle:   "github",
}

var theme = DarkTheme

// =============================================================================
// Datenbank
// =============================================================================

func loadScripts(dbPath string) ([]Script, error) {
	conn, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	rows, err := conn.Query(`
		SELECT id, database_id, database_name, table_id, table_name,
		       element_id, element_name, code_type, code_category, code, line_count
		FROM scripts
		ORDER BY database_name, table_name, element_name, code_type
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

// =============================================================================
// Spaltenbreiten
// =============================================================================

type ColumnWidths struct {
	Database int
	Table    int
	Element  int
	Type     int
	Category int
}

func calculateWidths(scripts []Script) ColumnWidths {
	w := ColumnWidths{Database: 8, Table: 7, Element: 7, Type: 3, Category: 8}

	for _, s := range scripts {
		if len(s.DatabaseName) > w.Database {
			w.Database = len(s.DatabaseName)
		}
		if len(s.TableName) > w.Table {
			w.Table = len(s.TableName)
		}
		elem := s.ElementName
		if elem == "" {
			elem = "(Tabelle)"
		}
		if len(elem) > w.Element {
			w.Element = len(elem)
		}
		if len(s.CodeType) > w.Type {
			w.Type = len(s.CodeType)
		}
		if len(s.CodeCategory) > w.Category {
			w.Category = len(s.CodeCategory)
		}
	}

	// Maximalwerte
	if w.Database > 30 {
		w.Database = 30
	}
	if w.Table > 30 {
		w.Table = 30
	}
	if w.Element > 30 {
		w.Element = 30
	}
	if w.Type > 15 {
		w.Type = 15
	}
	if w.Category > 12 {
		w.Category = 12
	}

	return w
}

// =============================================================================
// Filter
// =============================================================================

func filterScripts(scripts []Script, filter string) []Script {
	filter = strings.TrimSpace(filter)
	if filter == "" {
		return scripts
	}

	orGroups := strings.Split(filter, " OR ")
	var result []Script

	for _, script := range scripts {
		searchText := strings.ToLower(
			script.DatabaseName + " " +
				script.TableName + " " +
				script.ElementName + " " +
				script.CodeType + " " +
				script.CodeCategory + " " +
				script.Code,
		)

		for _, orGroup := range orGroups {
			orGroup = strings.TrimSpace(orGroup)
			if orGroup == "" {
				continue
			}

			andTerms := strings.Split(orGroup, " AND ")
			allMatch := true

			for _, term := range andTerms {
				term = strings.TrimSpace(strings.ToLower(term))
				if term != "" && !strings.Contains(searchText, term) {
					allMatch = false
					break
				}
			}

			if allMatch {
				result = append(result, script)
				break
			}
		}
	}
	return result
}

// =============================================================================
// Model
// =============================================================================

type Model struct {
	width, height int

	allScripts      []Script
	filteredScripts []Script
	selected        int
	scrollOffset    int

	filterInput textinput.Model
	filterText  string
	filtering   bool

	codeView    viewport.Model
	showingCode bool

	colWidths ColumnWidths
}

func NewModel(scripts []Script) Model {
	fi := textinput.New()
	fi.Placeholder = "Filter: Begriff AND Begriff OR Begriff..."
	fi.CharLimit = 200
	fi.Width = 80

	cv := viewport.New(80, 20)
	w := calculateWidths(scripts)

	return Model{
		allScripts:      scripts,
		filteredScripts: scripts,
		filterInput:     fi,
		codeView:        cv,
		colWidths:       w,
	}
}

// =============================================================================
// Key Bindings
// =============================================================================

var keys = struct {
	Up, Down, Enter, Back, Filter, Clear, Quit, PageUp, PageDown key.Binding
}{
	Up:       key.NewBinding(key.WithKeys("up", "k")),
	Down:     key.NewBinding(key.WithKeys("down", "j")),
	Enter:    key.NewBinding(key.WithKeys("enter")),
	Back:     key.NewBinding(key.WithKeys("esc")),
	Filter:   key.NewBinding(key.WithKeys("f", "/")),
	Clear:    key.NewBinding(key.WithKeys("c")),
	Quit:     key.NewBinding(key.WithKeys("q", "ctrl+c")),
	PageUp:   key.NewBinding(key.WithKeys("pgup", "ctrl+u")),
	PageDown: key.NewBinding(key.WithKeys("pgdown", "ctrl+d")),
}

// =============================================================================
// Bubble Tea
// =============================================================================

func (m Model) Init() tea.Cmd { return nil }

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmd tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.codeView.Width = msg.Width - 4
		m.codeView.Height = msg.Height - 6
		return m, nil

	case tea.KeyMsg:
		if m.filtering {
			switch {
			case key.Matches(msg, keys.Back):
				m.filtering = false
				m.filterInput.Blur()
			case key.Matches(msg, keys.Enter):
				m.filtering = false
				m.filterInput.Blur()
				m.filterText = m.filterInput.Value()
				m.applyFilter()
			default:
				m.filterInput, cmd = m.filterInput.Update(msg)
			}
			return m, cmd
		}

		if m.showingCode {
			switch {
			case key.Matches(msg, keys.Back), key.Matches(msg, keys.Enter):
				m.showingCode = false
			case key.Matches(msg, keys.Quit):
				return m, tea.Quit
			default:
				m.codeView, cmd = m.codeView.Update(msg)
			}
			return m, cmd
		}

		switch {
		case key.Matches(msg, keys.Quit):
			return m, tea.Quit
		case key.Matches(msg, keys.Filter):
			m.filtering = true
			m.filterInput.Focus()
			return m, textinput.Blink
		case key.Matches(msg, keys.Clear):
			m.filterText = ""
			m.filterInput.SetValue("")
			m.filteredScripts = m.allScripts
			m.selected = 0
			m.scrollOffset = 0
			m.colWidths = calculateWidths(m.allScripts)
		case key.Matches(msg, keys.Up):
			if m.selected > 0 {
				m.selected--
				m.adjustScroll()
			}
		case key.Matches(msg, keys.Down):
			if m.selected < len(m.filteredScripts)-1 {
				m.selected++
				m.adjustScroll()
			}
		case key.Matches(msg, keys.PageUp):
			m.selected -= 5
			if m.selected < 0 {
				m.selected = 0
			}
			m.adjustScroll()
		case key.Matches(msg, keys.PageDown):
			m.selected += 5
			if m.selected >= len(m.filteredScripts) {
				m.selected = len(m.filteredScripts) - 1
			}
			if m.selected < 0 {
				m.selected = 0
			}
			m.adjustScroll()
		case key.Matches(msg, keys.Enter):
			if len(m.filteredScripts) > 0 {
				s := m.filteredScripts[m.selected]
				m.codeView.SetContent(m.formatCode(s))
				m.codeView.GotoTop()
				m.showingCode = true
			}
		}
	}
	return m, nil
}

func (m *Model) adjustScroll() {
	visible := m.visibleRows()
	if m.selected < m.scrollOffset {
		m.scrollOffset = m.selected
	}
	if m.selected >= m.scrollOffset+visible {
		m.scrollOffset = m.selected - visible + 1
	}
}

func (m *Model) visibleRows() int {
	rows := (m.height - 12) / 10 // Ca. 10 Zeilen pro Script
	if rows < 1 {
		rows = 1
	}
	return rows
}

func (m *Model) applyFilter() {
	if m.filterText == "" {
		m.filteredScripts = m.allScripts
	} else {
		m.filteredScripts = filterScripts(m.allScripts, m.filterText)
	}
	m.selected = 0
	m.scrollOffset = 0
	m.colWidths = calculateWidths(m.filteredScripts)
}

func (m Model) View() string {
	if m.width == 0 {
		return "Lade..."
	}
	if m.showingCode {
		return m.viewCode()
	}
	return m.viewList()
}

func (m Model) viewList() string {
	var b strings.Builder

	// Titel
	total, filtered := len(m.allScripts), len(m.filteredScripts)
	title := fmt.Sprintf("📜 Ninox Scripts (%d", filtered)
	if filtered != total {
		title += fmt.Sprintf(" von %d", total)
	}
	title += ")"

	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.Primary).
		Padding(0, 2)
	b.WriteString(titleStyle.Render(title) + "\n\n")

	// Filter
	if m.filtering {
		box := lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(theme.Primary).
			Padding(0, 1).
			Render("🔍 " + m.filterInput.View())
		b.WriteString(box + "\n\n")
	} else if m.filterText != "" {
		info := lipgloss.NewStyle().Foreground(theme.TextMuted).
			Render(fmt.Sprintf("  Filter: %s  │  c = löschen", m.filterText))
		b.WriteString(info + "\n\n")
	}

	// Spalten-Header
	w := m.colWidths
	header := fmt.Sprintf("  %-*s │ %-*s │ %-*s │ %-*s │ %s",
		w.Database, "Datenbank",
		w.Table, "Tabelle",
		w.Element, "Element",
		w.Type, "Typ",
		"Kategorie")
	headerStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.Primary)
	b.WriteString(headerStyle.Render(header) + "\n")

	sep := strings.Repeat("─", m.width-4)
	b.WriteString(lipgloss.NewStyle().Foreground(theme.Border).Render(sep) + "\n")

	// Scripts
	if len(m.filteredScripts) == 0 {
		noData := lipgloss.NewStyle().Foreground(theme.TextMuted).Padding(1).
			Render("Keine Scripts gefunden.")
		b.WriteString(noData + "\n")
	} else {
		visible := m.visibleRows()
		start := m.scrollOffset
		end := start + visible
		if end > len(m.filteredScripts) {
			end = len(m.filteredScripts)
		}

		for i := start; i < end; i++ {
			b.WriteString(m.renderRow(i) + "\n")
		}
	}

	// Footer
	b.WriteString("\n")
	pos := fmt.Sprintf(" %d/%d ", m.selected+1, len(m.filteredScripts))
	help := " ↑↓ Nav │ Enter Code │ f Filter │ c Clear │ q Quit "

	posStyle := lipgloss.NewStyle().Foreground(theme.Primary)
	helpStyle := lipgloss.NewStyle().Foreground(theme.TextMuted)
	b.WriteString(posStyle.Render(pos) + helpStyle.Render(help))

	return b.String()
}

func (m Model) renderRow(idx int) string {
	s := m.filteredScripts[idx]
	sel := idx == m.selected
	w := m.colWidths

	elem := s.ElementName
	if elem == "" {
		elem = "(Tabelle)"
	}

	prefix := "  "
	if sel {
		prefix = "▶ "
	}

	// Header-Zeile
	line := fmt.Sprintf("%s%-*s │ %-*s │ %-*s │ %-*s │ %s",
		prefix,
		w.Database, trunc(s.DatabaseName, w.Database),
		w.Table, trunc(s.TableName, w.Table),
		w.Element, trunc(elem, w.Element),
		w.Type, trunc(s.CodeType, w.Type),
		trunc(s.CodeCategory, w.Category))

	lineStyle := lipgloss.NewStyle().Foreground(theme.Text)
	if sel {
		lineStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(theme.SelectionFg).
			Background(theme.SelectionBg)
	}

	// Code-Box
	codeWidth := m.width - 8
	if codeWidth < 40 {
		codeWidth = 40
	}

	codeLines := strings.Split(s.Code, "\n")
	preview := m.codePreview(codeLines, codeWidth, sel)

	borderColor := theme.Border
	if sel {
		borderColor = theme.Primary
	}

	codeBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(borderColor).
		Padding(0, 1).
		Width(codeWidth).
		Render(preview)

	return lineStyle.Render(line) + "\n" + codeBox
}

func (m Model) codePreview(lines []string, width int, sel bool) string {
	var b strings.Builder

	maxLines := len(lines)
	if maxLines > 12 {
		maxLines = 12
	}

	numStyle := lipgloss.NewStyle().Foreground(theme.TextMuted)
	codeStyle := lipgloss.NewStyle().Foreground(theme.Text)
	if sel {
		codeStyle = codeStyle.Foreground(theme.Secondary)
	}

	for i := 0; i < maxLines; i++ {
		num := fmt.Sprintf("%3d │ ", i+1)
		line := lines[i]
		if len(line) > width-10 {
			line = line[:width-13] + "..."
		}
		b.WriteString(numStyle.Render(num) + codeStyle.Render(line))
		if i < maxLines-1 {
			b.WriteString("\n")
		}
	}

	if len(lines) > maxLines {
		more := fmt.Sprintf("\n     ... (+%d Zeilen)", len(lines)-maxLines)
		b.WriteString(lipgloss.NewStyle().Foreground(theme.TextMuted).Render(more))
	}

	return b.String()
}

func (m Model) formatCode(s Script) string {
	var b strings.Builder

	// Header
	hdr := lipgloss.NewStyle().Bold(true).Foreground(theme.Primary)
	b.WriteString(hdr.Render("═══════════════════════════════════════════════════════════") + "\n")
	b.WriteString(hdr.Render(fmt.Sprintf("  Datenbank:  %s", s.DatabaseName)) + "\n")
	b.WriteString(hdr.Render(fmt.Sprintf("  Tabelle:    %s", s.TableName)) + "\n")
	if s.ElementName != "" {
		b.WriteString(hdr.Render(fmt.Sprintf("  Element:    %s", s.ElementName)) + "\n")
	}
	b.WriteString(hdr.Render(fmt.Sprintf("  Typ:        %s (%s)", s.CodeType, s.CodeCategory)) + "\n")
	b.WriteString(hdr.Render(fmt.Sprintf("  Zeilen:     %d", s.LineCount)) + "\n")
	b.WriteString(hdr.Render("═══════════════════════════════════════════════════════════") + "\n\n")

	// Syntax-Highlighting
	b.WriteString(highlightCode(s.Code))

	return b.String()
}

func (m Model) viewCode() string {
	var b strings.Builder

	title := lipgloss.NewStyle().
		Bold(true).
		Foreground(theme.SelectionFg).
		Background(theme.Primary).
		Padding(0, 2).
		Render("💻 Vollständiger Code")

	b.WriteString(title + "\n\n")
	b.WriteString(m.codeView.View() + "\n")

	scroll := fmt.Sprintf(" %d%% ", int(m.codeView.ScrollPercent()*100))
	help := " ↑↓ Scroll │ Esc/Enter Zurück │ q Beenden "
	b.WriteString(lipgloss.NewStyle().Foreground(theme.Primary).Render(scroll))
	b.WriteString(lipgloss.NewStyle().Foreground(theme.TextMuted).Render(help))

	return b.String()
}

// =============================================================================
// Hilfsfunktionen
// =============================================================================

func trunc(s string, max int) string {
	if len(s) <= max {
		return s
	}
	if max <= 3 {
		return s[:max]
	}
	return s[:max-3] + "..."
}

func highlightCode(code string) string {
	lexer := lexers.Get("javascript")
	if lexer == nil {
		lexer = lexers.Fallback
	}
	lexer = chroma.Coalesce(lexer)

	style := styles.Get(theme.CodeStyle)
	if style == nil {
		style = styles.Fallback
	}

	formatter := formatters.Get("terminal256")
	if formatter == nil {
		formatter = formatters.Fallback
	}

	iter, err := lexer.Tokenise(nil, code)
	if err != nil {
		return code
	}

	var buf bytes.Buffer
	if err := formatter.Format(&buf, style, iter); err != nil {
		return code
	}

	lines := strings.Split(buf.String(), "\n")
	var result strings.Builder
	numStyle := lipgloss.NewStyle().Foreground(theme.TextMuted)

	for i, line := range lines {
		num := fmt.Sprintf("%4d │ ", i+1)
		result.WriteString(numStyle.Render(num) + line + "\n")
	}

	return result.String()
}

// =============================================================================
// Main
// =============================================================================

func main() {
	dbPath := "ninox_schema.db"

	args := os.Args[1:]
	for _, arg := range args {
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

	if _, err := os.Stat(dbPath); os.IsNotExist(err) {
		fmt.Printf("❌ Datenbank nicht gefunden: %s\n", dbPath)
		fmt.Println("   Bitte zuerst Daten extrahieren.")
		os.Exit(1)
	}

	scripts, err := loadScripts(dbPath)
	if err != nil {
		fmt.Printf("❌ Fehler: %v\n", err)
		os.Exit(1)
	}

	model := NewModel(scripts)
	p := tea.NewProgram(model, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Printf("Fehler: %v\n", err)
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Println("Ninox Scripts Viewer")
	fmt.Println("")
	fmt.Println("Zeigt alle Scripts in einer übersichtlichen Liste mit vollständigem Code.")
	fmt.Println("")
	fmt.Println("Verwendung:")
	fmt.Println("  ninox-scripts [optionen] [datenbank.db]")
	fmt.Println("")
	fmt.Println("Optionen:")
	fmt.Println("  --dark, -d   Dunkles Farbschema (Standard)")
	fmt.Println("  --light, -l  Helles Farbschema")
	fmt.Println("  --help, -h   Diese Hilfe")
	fmt.Println("")
	fmt.Println("Tasten:")
	fmt.Println("  ↑/k ↓/j      Navigation")
	fmt.Println("  Enter        Vollständigen Code anzeigen")
	fmt.Println("  f /          Filter eingeben")
	fmt.Println("  c            Filter löschen")
	fmt.Println("  PgUp/PgDn    Seitenweise scrollen")
	fmt.Println("  q Ctrl+C     Beenden")
	fmt.Println("")
	fmt.Println("Filter:")
	fmt.Println("  text         Einfache Suche")
	fmt.Println("  A AND B      Beide müssen vorkommen")
	fmt.Println("  A OR B       Einer muss vorkommen")
}
