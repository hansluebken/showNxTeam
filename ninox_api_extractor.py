#!/usr/bin/env python3
"""
Ninox API Schema & Script Extractor
====================================
Extrahiert direkt von der Ninox REST API:
- Alle Tabellen und Felder
- Alle Verknüpfungen (N:1, 1:N, Cross-DB)
- Alle Scripts und Formeln
- Speichert in SQLite mit Volltextsuche

Verwendung:
    python ninox_api_extractor.py --domain https://ninox.example.com \
                                  --team TEAM_ID \
                                  --apikey API_KEY \
                                  --output ninox_schema.db

Oder mit config.yaml:
    python ninox_api_extractor.py --config config.yaml --env dev

Danach Suche:
    python ninox_api_extractor.py --db ninox_schema.db search "select Kunden"
    python ninox_api_extractor.py --db ninox_schema.db deps "Aufträge"
    python ninox_api_extractor.py --db ninox_schema.db stats
"""

import os
import re
import json
import sqlite3
import requests
import logging
import argparse
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from urllib.parse import urljoin

# .env Datei laden (falls vorhanden)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv nicht installiert - Umgebungsvariablen direkt verwenden

# Syntax-Highlighting ist jetzt integriert
SYNTAX_HIGHLIGHTING_AVAILABLE = True

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Ninox Lexer & Syntax Highlighting (integriert)
# =============================================================================

class TokenType(Enum):
    """Token types for Ninox syntax"""
    KEYWORD = "keyword"
    OPERATOR = "operator"
    STRING = "string"
    NUMBER = "number"
    COMMENT = "comment"
    FUNCTION = "function"
    BUILTIN = "builtin"
    FIELD = "field"
    TABLE = "table"
    PUNCTUATION = "punctuation"
    IDENTIFIER = "identifier"
    WHITESPACE = "whitespace"
    NEWLINE = "newline"


@dataclass
class Token:
    """Represents a single token"""
    type: TokenType
    value: str
    start: int
    end: int


# Ninox keywords
KEYWORDS = {
    # Control flow
    'if', 'then', 'else', 'end', 'switch', 'case', 'default',
    'for', 'do', 'while', 'break', 'continue',
    'try', 'catch', 'throw',

    # Declarations
    'let', 'var', 'function',

    # Operators
    'and', 'or', 'not', 'in', 'like',

    # Values
    'true', 'false', 'null', 'this', 'me',

    # Context modifiers
    'as', 'database', 'server', 'transaction', 'user',

    # Data operations
    'select', 'from', 'where', 'order', 'by', 'group', 'limit',
    'asc', 'desc', 'distinct',
}

# Ninox built-in functions
BUILTIN_FUNCTIONS = {
    # Record operations
    'create', 'delete', 'duplicate', 'record', 'records',
    'first', 'last', 'item', 'count', 'sum', 'avg', 'min', 'max',

    # String functions
    'text', 'number', 'upper', 'lower', 'trim', 'length',
    'substr', 'replace', 'split', 'join', 'contains',
    'format', 'formatNumber', 'parseNumber',

    # Date functions
    'today', 'now', 'date', 'time', 'datetime',
    'year', 'month', 'day', 'hour', 'minute', 'second',
    'weekday', 'week', 'quarter',
    'dateAdd', 'dateDiff', 'dateFormat',
    'startOfDay', 'endOfDay', 'startOfWeek', 'endOfWeek',
    'startOfMonth', 'endOfMonth', 'startOfYear', 'endOfYear',

    # Math functions
    'abs', 'ceil', 'floor', 'round', 'sqrt', 'pow',
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan',
    'log', 'exp', 'random',

    # Array functions
    'array', 'unique', 'sort', 'reverse', 'slice',
    'concat', 'indexOf', 'includes', 'filter', 'map',

    # UI functions
    'alert', 'confirm', 'prompt', 'dialog',
    'popupRecord', 'openRecord', 'closePopup',
    'openPrintLayout', 'printRecord',

    # File functions
    'importFile', 'exportFile', 'downloadFile',
    'importCSV', 'importJSON', 'exportCSV', 'exportJSON',

    # HTTP functions
    'http', 'httpGet', 'httpPost', 'httpPut', 'httpDelete',

    # Email
    'sendEmail', 'email',

    # Utility
    'debug', 'print', 'sleep', 'eval',
    'typeof', 'isnull', 'isempty', 'isEmpty',
    'coalesce', 'choose', 'switch',

    # UI State
    'setStyle', 'getStyle', 'focus', 'blur',

    # Navigation
    'navigate', 'openUrl', 'openTable', 'openView',

    # User
    'userId', 'userName', 'userEmail', 'userRoles',
    'hasRole', 'isAdmin',

    # Database info
    'databaseId', 'databaseName', 'tableId', 'tableName',
    'fieldId', 'fieldName',

    # Archiving
    'archive', 'unarchive', 'isArchived',

    # Clipboard
    'copyToClipboard', 'readFromClipboard',

    # JSON
    'parseJSON', 'formatJSON', 'json',

    # Colors
    'rgb', 'rgba', 'hex', 'color',

    # Location
    'location', 'geoDistance',
}

# CSS classes for each token type
TOKEN_CSS_CLASSES = {
    TokenType.KEYWORD: 'nx-keyword',
    TokenType.OPERATOR: 'nx-operator',
    TokenType.STRING: 'nx-string',
    TokenType.NUMBER: 'nx-number',
    TokenType.COMMENT: 'nx-comment',
    TokenType.FUNCTION: 'nx-function',
    TokenType.BUILTIN: 'nx-builtin',
    TokenType.FIELD: 'nx-field',
    TokenType.TABLE: 'nx-table',
    TokenType.PUNCTUATION: 'nx-punctuation',
    TokenType.IDENTIFIER: 'nx-identifier',
    TokenType.WHITESPACE: '',
    TokenType.NEWLINE: '',
}

# Color scheme (GitHub Light theme)
CSS_STYLES = """
<style>
.ninox-code {
    font-family: 'Fira Code', 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 14px;
    line-height: 1.6;
    background: #ffffff;
    color: #24292e;
    padding: 0;
    border-radius: 0;
    overflow: auto;
    tab-size: 4;
    border: none;
    height: 100%;
    width: 100%;
}
.ninox-code-table {
    border-collapse: collapse;
    width: 100%;
    margin: 0;
}
.nx-line-number {
    color: #6e7781;
    text-align: right;
    padding: 0 12px;
    user-select: none;
    border-right: 1px solid #e1e4e8;
    background: #f6f8fa;
    min-width: 50px;
    vertical-align: top;
    font-size: 12px;
}
.nx-line-content {
    padding: 0 16px;
    white-space: pre;
    vertical-align: top;
    text-align: left;
}
.nx-line-content:hover {
    background: #f6f8fa;
}
/* Token colors - GitHub Light theme */
.nx-keyword {
    color: #d73a49;
    font-weight: 600;
}
.nx-operator {
    color: #005cc5;
}
.nx-string {
    color: #032f62;
}
.nx-number {
    color: #005cc5;
}
.nx-comment {
    color: #6a737d;
    font-style: italic;
}
.nx-function {
    color: #6f42c1;
    font-weight: 500;
}
.nx-builtin {
    color: #005cc5;
    font-weight: 500;
}
.nx-field {
    color: #24292e;
}
.nx-table {
    color: #005cc5;
}
.nx-punctuation {
    color: #24292e;
}
.nx-identifier {
    color: #24292e;
}
/* Highlight matches in search */
.nx-highlight {
    background: #fff3cd;
    border-radius: 2px;
    padding: 1px 2px;
}
/* Current line indicator */
.nx-current-line {
    background: #f1f8ff !important;
}
</style>
"""


def tokenize(code: str) -> List[Token]:
    """
    Tokenize Ninox code into a list of tokens.

    Args:
        code: Ninox code string

    Returns:
        List of Token objects
    """
    tokens = []
    pos = 0

    while pos < len(code):
        token = None

        # Newline
        if code[pos] == '\n':
            token = Token(TokenType.NEWLINE, '\n', pos, pos + 1)
            pos += 1

        # Whitespace (not newline)
        elif code[pos] in ' \t\r':
            end = pos
            while end < len(code) and code[end] in ' \t\r':
                end += 1
            token = Token(TokenType.WHITESPACE, code[pos:end], pos, end)
            pos = end

        # Single-line comment //
        elif code[pos:pos+2] == '//':
            end = code.find('\n', pos)
            if end == -1:
                end = len(code)
            token = Token(TokenType.COMMENT, code[pos:end], pos, end)
            pos = end

        # Multi-line comment --- ... ---
        elif code[pos:pos+3] == '---':
            end = code.find('---', pos + 3)
            if end == -1:
                end = len(code)
            else:
                end += 3
            token = Token(TokenType.COMMENT, code[pos:end], pos, end)
            pos = end

        # String (double quotes)
        elif code[pos] == '"':
            end = pos + 1
            while end < len(code):
                if code[end] == '\\' and end + 1 < len(code):
                    end += 2
                elif code[end] == '"':
                    end += 1
                    break
                else:
                    end += 1
            token = Token(TokenType.STRING, code[pos:end], pos, end)
            pos = end

        # String (single quotes)
        elif code[pos] == "'":
            end = pos + 1
            while end < len(code):
                if code[end] == '\\' and end + 1 < len(code):
                    end += 2
                elif code[end] == "'":
                    end += 1
                    break
                else:
                    end += 1
            token = Token(TokenType.STRING, code[pos:end], pos, end)
            pos = end

        # Number
        elif code[pos].isdigit() or (code[pos] == '.' and pos + 1 < len(code) and code[pos+1].isdigit()):
            end = pos
            has_dot = False
            while end < len(code):
                if code[end].isdigit():
                    end += 1
                elif code[end] == '.' and not has_dot:
                    has_dot = True
                    end += 1
                elif code[end] in 'eE' and end + 1 < len(code) and (code[end+1].isdigit() or code[end+1] in '+-'):
                    end += 1
                    if end < len(code) and code[end] in '+-':
                        end += 1
                else:
                    break
            token = Token(TokenType.NUMBER, code[pos:end], pos, end)
            pos = end

        # Assignment operator :=
        elif code[pos:pos+2] == ':=':
            token = Token(TokenType.OPERATOR, ':=', pos, pos + 2)
            pos += 2

        # Comparison operators
        elif code[pos:pos+2] in ('<=', '>=', '!=', '<>'):
            token = Token(TokenType.OPERATOR, code[pos:pos+2], pos, pos + 2)
            pos += 2

        # Single char operators
        elif code[pos] in '+-*/%=<>':
            token = Token(TokenType.OPERATOR, code[pos], pos, pos + 1)
            pos += 1

        # Punctuation
        elif code[pos] in '()[]{},.;:':
            token = Token(TokenType.PUNCTUATION, code[pos], pos, pos + 1)
            pos += 1

        # Identifier or keyword
        elif code[pos].isalpha() or code[pos] == '_':
            end = pos
            while end < len(code) and (code[end].isalnum() or code[end] == '_'):
                end += 1
            word = code[pos:end]
            word_lower = word.lower()

            # Check if it's a keyword
            if word_lower in KEYWORDS:
                token = Token(TokenType.KEYWORD, word, pos, end)
            # Check if it's a built-in function (followed by parenthesis)
            elif word_lower in BUILTIN_FUNCTIONS:
                # Look ahead for (
                lookahead = end
                while lookahead < len(code) and code[lookahead] in ' \t':
                    lookahead += 1
                if lookahead < len(code) and code[lookahead] == '(':
                    token = Token(TokenType.BUILTIN, word, pos, end)
                else:
                    token = Token(TokenType.IDENTIFIER, word, pos, end)
            # Check for table reference (uppercase letters/numbers pattern like A, B3, ZZ)
            elif re.match(r'^[A-Z][A-Z0-9]{0,3}$', word):
                # Could be a table or field ID
                # Look ahead for dot to determine if it's a table reference
                lookahead = end
                while lookahead < len(code) and code[lookahead] in ' \t':
                    lookahead += 1
                if lookahead < len(code) and code[lookahead] == '.':
                    token = Token(TokenType.TABLE, word, pos, end)
                else:
                    token = Token(TokenType.FIELD, word, pos, end)
            else:
                token = Token(TokenType.IDENTIFIER, word, pos, end)

            pos = end

        # Unknown character - treat as identifier
        else:
            token = Token(TokenType.IDENTIFIER, code[pos], pos, pos + 1)
            pos += 1

        if token:
            tokens.append(token)

    return tokens


def escape_html(text: str) -> str:
    """Escape HTML special characters"""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def highlight_code(
    code: str,
    highlight_text: Optional[str] = None,
    show_line_numbers: bool = True,
    max_height: str = "calc(100vh - 380px)"
) -> str:
    """
    Generate HTML with syntax highlighting for Ninox code.

    Args:
        code: Ninox code to highlight
        highlight_text: Optional text to highlight (for search results)
        show_line_numbers: Whether to show line numbers
        max_height: CSS max-height for the container

    Returns:
        HTML string with syntax highlighted code
    """
    if not code:
        return '<div class="ninox-code"><span class="nx-comment">// No code</span></div>'

    tokens = tokenize(code)

    # Build highlighted HTML for each line
    lines = ['']
    current_line = 0

    for token in tokens:
        if token.type == TokenType.NEWLINE:
            lines.append('')
            current_line += 1
        else:
            css_class = TOKEN_CSS_CLASSES.get(token.type, '')
            escaped_value = escape_html(token.value)

            # Apply highlight if needed
            if highlight_text and highlight_text.lower() in token.value.lower():
                # Wrap matching text in highlight span
                pattern = re.compile(re.escape(highlight_text), re.IGNORECASE)
                escaped_value = pattern.sub(
                    lambda m: f'<span class="nx-highlight">{escape_html(m.group())}</span>',
                    token.value
                )
                escaped_value = escape_html(token.value)
                if highlight_text.lower() in token.value.lower():
                    # Find and wrap the match
                    idx = token.value.lower().find(highlight_text.lower())
                    if idx >= 0:
                        before = escape_html(token.value[:idx])
                        match = escape_html(token.value[idx:idx+len(highlight_text)])
                        after = escape_html(token.value[idx+len(highlight_text):])
                        escaped_value = f'{before}<span class="nx-highlight">{match}</span>{after}'

            if css_class:
                lines[current_line] += f'<span class="{css_class}">{escaped_value}</span>'
            else:
                lines[current_line] += escaped_value

    # Build final HTML
    html_parts = [CSS_STYLES]
    html_parts.append(f'<div class="ninox-code" style="max-height: {max_height};">')

    if show_line_numbers:
        html_parts.append('<table class="ninox-code-table">')
        for i, line in enumerate(lines, 1):
            html_parts.append(f'''
                <tr>
                    <td class="nx-line-number">{i}</td>
                    <td class="nx-line-content">{line or '&nbsp;'}</td>
                </tr>
            ''')
        html_parts.append('</table>')
    else:
        for line in lines:
            html_parts.append(f'<div class="nx-line-content">{line or "&nbsp;"}</div>')

    html_parts.append('</div>')

    return ''.join(html_parts)


def highlight_code_simple(code: str) -> str:
    """
    Simple one-line syntax highlighting without line numbers.
    Useful for inline code display.
    """
    if not code:
        return ''

    tokens = tokenize(code)
    html_parts = [CSS_STYLES, '<span class="ninox-code" style="display: inline; padding: 2px 6px;">']

    for token in tokens:
        if token.type == TokenType.NEWLINE:
            html_parts.append(' ')  # Replace newline with space
        else:
            css_class = TOKEN_CSS_CLASSES.get(token.type, '')
            escaped = escape_html(token.value)
            if css_class:
                html_parts.append(f'<span class="{css_class}">{escaped}</span>')
            else:
                html_parts.append(escaped)

    html_parts.append('</span>')
    return ''.join(html_parts)


def format_code(code: str, indent_size: int = 4) -> str:
    """
    Format Ninox code with proper indentation.

    Args:
        code: Ninox code to format
        indent_size: Number of spaces per indent level

    Returns:
        Formatted code string
    """
    if not code:
        return code

    # Keywords that increase indent
    indent_after = {'do', 'then', '{'}
    # Keywords that decrease indent before
    dedent_before = {'end', 'else', '}'}
    # Keywords that get their own line
    own_line = {'let', 'for', 'if', 'switch', 'case', 'else', 'end'}

    tokens = tokenize(code)
    result = []
    indent_level = 0
    line_start = True
    prev_token = None

    for token in tokens:
        value = token.value
        value_lower = value.lower() if token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER) else value

        # Handle dedent before certain keywords
        if token.type == TokenType.KEYWORD and value_lower in dedent_before:
            indent_level = max(0, indent_level - 1)

        if token.type == TokenType.PUNCTUATION and value == '}':
            indent_level = max(0, indent_level - 1)

        # Handle newlines
        if token.type == TokenType.NEWLINE:
            result.append('\n')
            line_start = True
            continue

        # Skip whitespace at line start (we'll add our own indent)
        if token.type == TokenType.WHITESPACE and line_start:
            continue

        # Add indent at line start
        if line_start and token.type not in (TokenType.WHITESPACE, TokenType.NEWLINE):
            result.append(' ' * (indent_level * indent_size))
            line_start = False

        # Check if we should add newline before certain keywords
        if token.type == TokenType.KEYWORD and value_lower in own_line:
            if not line_start and result and result[-1] not in '\n':
                result.append('\n')
                result.append(' ' * (indent_level * indent_size))

        # Add the token
        result.append(value)

        # Handle indent after certain keywords/punctuation
        if token.type == TokenType.KEYWORD and value_lower in indent_after:
            indent_level += 1
            result.append('\n')
            result.append(' ' * (indent_level * indent_size))
            line_start = False

        if token.type == TokenType.PUNCTUATION and value == '{':
            indent_level += 1
            result.append('\n')
            result.append(' ' * (indent_level * indent_size))
            line_start = False

        # Add newline after semicolon
        if token.type == TokenType.PUNCTUATION and value == ';':
            result.append('\n')
            line_start = True

        prev_token = token

    return ''.join(result).strip()


def get_code_preview(code: str, max_length: int = 100) -> str:
    """
    Get a short preview of code for display in lists.

    Args:
        code: Full code
        max_length: Maximum length of preview

    Returns:
        Shortened code preview
    """
    if not code:
        return ''

    # Replace newlines with spaces
    preview = ' '.join(code.split())

    if len(preview) > max_length:
        preview = preview[:max_length - 3] + '...'

    return preview


# =============================================================================
# Enums und Datenklassen
# =============================================================================

class RelationshipType(Enum):
    """Typen von Ninox-Verknüpfungen"""
    REFERENCE_N1 = "N:1"
    REFERENCE_1N = "1:N"
    REFERENCE_MN = "M:N"
    CROSS_DB = "CROSS_DB"
    FORMULA_REF = "FORMULA_REF"


class CodeCategory(Enum):
    """Kategorie des Codes"""
    GLOBAL = "global"
    TRIGGER = "trigger"
    FORMULA = "formula"
    BUTTON = "button"
    VISIBILITY = "visibility"
    PERMISSION = "permission"
    DYNAMIC_CHOICE = "dchoice"
    VALIDATION = "validation"
    REFERENCE = "reference"
    VIEW = "view"
    REPORT = "report"
    OTHER = "other"


# Code-Felder nach Ebene
DATABASE_CODE_FIELDS = {
    'afterOpen': CodeCategory.TRIGGER,
    'beforeOpen': CodeCategory.TRIGGER,
    'globalCode': CodeCategory.GLOBAL,
}

TABLE_CODE_FIELDS = {
    'afterCreate': CodeCategory.TRIGGER,
    'afterUpdate': CodeCategory.TRIGGER,
    'afterDelete': CodeCategory.TRIGGER,
    'beforeDelete': CodeCategory.TRIGGER,
    'canRead': CodeCategory.PERMISSION,
    'canWrite': CodeCategory.PERMISSION,
    'canCreate': CodeCategory.PERMISSION,
    'canDelete': CodeCategory.PERMISSION,
    'printout': CodeCategory.OTHER,
}

FIELD_CODE_FIELDS = {
    'fn': CodeCategory.FORMULA,
    'afterUpdate': CodeCategory.TRIGGER,
    'afterCreate': CodeCategory.TRIGGER,
    'constraint': CodeCategory.VALIDATION,
    'dchoiceValues': CodeCategory.DYNAMIC_CHOICE,
    'dchoiceCaption': CodeCategory.DYNAMIC_CHOICE,
    'dchoiceColor': CodeCategory.DYNAMIC_CHOICE,
    'dchoiceIcon': CodeCategory.DYNAMIC_CHOICE,
    'referenceFormat': CodeCategory.REFERENCE,
    'visibility': CodeCategory.VISIBILITY,
    'onClick': CodeCategory.BUTTON,
    'onDoubleClick': CodeCategory.BUTTON,
    'canRead': CodeCategory.PERMISSION,
    'canWrite': CodeCategory.PERMISSION,
    'validation': CodeCategory.VALIDATION,
    'color': CodeCategory.OTHER,
}


@dataclass
class Relationship:
    """Repräsentiert eine Verknüpfung zwischen Tabellen"""
    database_id: str
    database_name: str
    source_table_id: str
    source_table_name: str
    source_field_id: str
    source_field_name: str
    target_table_id: str
    target_table_name: str
    target_database_id: Optional[str] = None
    target_database_name: Optional[str] = None
    relationship_type: str = "N:1"
    is_composition: bool = False
    reverse_field_name: Optional[str] = None
    found_in_code_type: Optional[str] = None
    found_in_code: Optional[str] = None

    def __hash__(self):
        return hash((
            self.database_id,
            self.source_table_name,
            self.source_field_name,
            self.target_table_name,
            self.relationship_type
        ))


@dataclass
class CodeLocation:
    """Repräsentiert eine Code-Stelle in Ninox"""
    team_id: str
    team_name: str
    database_id: str
    database_name: str
    table_id: Optional[str]
    table_name: Optional[str]
    element_id: Optional[str]
    element_name: Optional[str]
    code_type: str
    code_category: str
    code: str
    code_original: Optional[str] = None  # Original mit IDs
    line_count: int = 0

    def __post_init__(self):
        if self.code:
            self.line_count = len(self.code.split('\n'))


# =============================================================================
# Ninox API Client
# =============================================================================

class NinoxAPIClient:
    """Client für die Ninox REST API"""

    def __init__(self, domain: str, team_id: str, api_key: str, team_name: str = None):
        self.domain = domain.rstrip('/')
        self.team_id = team_id
        self.team_name = team_name or team_id  # Fallback auf ID wenn kein Name
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Führt einen API-Request aus"""
        url = f"{self.domain}/v1/{endpoint}"
        logger.debug(f"{method} {url}")
        
        response = self.session.request(method, url, **kwargs)
        response.raise_for_status()
        
        if response.content:
            return response.json()
        return None
    
    def get_teams(self) -> List[Dict]:
        """Listet alle Teams/Workspaces"""
        return self._request('GET', 'teams') or []

    def get_team_name(self) -> str:
        """Holt den Team-Namen von der API basierend auf team_id"""
        teams = self.get_teams()
        for team in teams:
            if team.get('id') == self.team_id:
                return team.get('name', self.team_id)
        return self.team_id  # Fallback auf ID

    def get_databases(self) -> List[Dict]:
        """Listet alle Datenbanken im Team"""
        return self._request('GET', f'teams/{self.team_id}/databases') or []
    
    def get_database_schema(self, db_id: str) -> Dict:
        """Holt das komplette Schema einer Datenbank.

        Der Parameter formatScripts=T sorgt dafür, dass Ninox die Scripts
        mit lesbaren Feldnamen statt internen IDs zurückgibt.
        """
        return self._request('GET', f'teams/{self.team_id}/databases/{db_id}?formatScripts=T') or {}
    
    def get_tables(self, db_id: str) -> List[Dict]:
        """Holt alle Tabellen einer Datenbank"""
        return self._request('GET', f'teams/{self.team_id}/databases/{db_id}/tables') or []
    
    def get_table_schema(self, db_id: str, table_id: str) -> Dict:
        """Holt das Schema einer einzelnen Tabelle"""
        return self._request('GET', f'teams/{self.team_id}/databases/{db_id}/tables/{table_id}') or {}
    
    def get_views(self, db_id: str) -> List[Dict]:
        """Holt alle Views einer Datenbank"""
        try:
            return self._request('GET', f'teams/{self.team_id}/databases/{db_id}/views') or []
        except:
            return []


# =============================================================================
# Schema Extractor
# =============================================================================

class NinoxSchemaExtractor:
    """
    Extrahiert Schema, Verknüpfungen und Scripts aus der Ninox API
    und speichert sie in einer durchsuchbaren SQLite-Datenbank.
    """
    
    # Regex-Pattern für Tabellen-Referenzen in Ninox-Code
    TABLE_REFERENCE_PATTERNS = [
        (r"select\s+([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)", "select"),
        (r"select\s+'([^']+)'", "select"),
        (r'select\s+"([^"]+)"', "select"),
        (r"first\s*\(\s*([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)", "first"),
        (r"first\s*\(\s*'([^']+)'", "first"),
        (r"last\s*\(\s*([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)", "last"),
        (r"count\s*\(\s*([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)", "count"),
        (r"(?:sum|max|min|avg|cnt)\s*\(\s*([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)\.([A-Za-z_][A-Za-z0-9_äöüÄÖÜß]*)", "aggregate"),
    ]
    
    def __init__(self, api_client: NinoxAPIClient, db_path: str = "ninox_schema.db"):
        self.api = api_client
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        
    def init_database(self):
        """Initialisiert die SQLite-Datenbank"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        
        cursor = self.conn.cursor()
        
        # Datenbanken
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS databases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version INTEGER,
                color TEXT,
                icon TEXT,
                table_count INTEGER DEFAULT 0,
                code_count INTEGER DEFAULT 0,
                extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabellen
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_id TEXT NOT NULL,
                table_id TEXT NOT NULL,
                name TEXT NOT NULL,
                caption TEXT,
                icon TEXT,
                hidden INTEGER DEFAULT 0,
                field_count INTEGER DEFAULT 0,
                UNIQUE(database_id, table_id),
                FOREIGN KEY (database_id) REFERENCES databases(id)
            )
        """)
        
        # Felder
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_id TEXT NOT NULL,
                table_id TEXT NOT NULL,
                field_id TEXT NOT NULL,
                name TEXT NOT NULL,
                caption TEXT,
                base_type TEXT,
                is_required INTEGER DEFAULT 0,
                ref_table_id TEXT,
                ref_table_name TEXT,
                ref_database_id TEXT,
                is_composition INTEGER DEFAULT 0,
                has_formula INTEGER DEFAULT 0,
                UNIQUE(database_id, table_id, field_id),
                FOREIGN KEY (database_id) REFERENCES databases(id)
            )
        """)
        
        # Verknüpfungen
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_id TEXT NOT NULL,
                database_name TEXT,
                source_table_id TEXT NOT NULL,
                source_table_name TEXT NOT NULL,
                source_field_id TEXT,
                source_field_name TEXT,
                target_table_id TEXT,
                target_table_name TEXT NOT NULL,
                target_database_id TEXT,
                target_database_name TEXT,
                relationship_type TEXT NOT NULL,
                is_composition INTEGER DEFAULT 0,
                reverse_field_name TEXT,
                found_in_code_type TEXT,
                found_in_code TEXT,
                FOREIGN KEY (database_id) REFERENCES databases(id)
            )
        """)
        
        # Scripts/Code
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL,
                team_name TEXT,
                database_id TEXT NOT NULL,
                database_name TEXT,
                table_id TEXT,
                table_name TEXT,
                element_id TEXT,
                element_name TEXT,
                code_type TEXT NOT NULL,
                code_category TEXT,
                code TEXT NOT NULL,
                code_original TEXT,
                line_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (database_id) REFERENCES databases(id)
            )
        """)

        # Cross-Database-Abhängigkeiten
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS script_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_id INTEGER NOT NULL,
                source_database_id TEXT NOT NULL,
                source_database_name TEXT,
                target_database_name TEXT NOT NULL,
                reference_type TEXT NOT NULL,
                code_snippet TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
                FOREIGN KEY (source_database_id) REFERENCES databases(id)
            )
        """)

        # Volltextsuche für Scripts
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS scripts_fts USING fts5(
                code,
                team_name,
                database_name,
                table_name,
                element_name,
                code_type,
                content='scripts',
                content_rowid='id'
            )
        """)

        # FTS Trigger
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS scripts_ai AFTER INSERT ON scripts BEGIN
                INSERT INTO scripts_fts(rowid, code, team_name, database_name, table_name, element_name, code_type)
                VALUES (new.id, new.code, new.team_name, new.database_name, new.table_name, new.element_name, new.code_type);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS scripts_ad AFTER DELETE ON scripts BEGIN
                INSERT INTO scripts_fts(scripts_fts, rowid, code, team_name, database_name, table_name, element_name, code_type)
                VALUES ('delete', old.id, old.code, old.team_name, old.database_name, old.table_name, old.element_name, old.code_type);
            END
        """)

        # Indizes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scripts_team ON scripts(team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scripts_db ON scripts(database_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scripts_table ON scripts(table_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scripts_type ON scripts(code_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_table_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_table_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fields_ref ON fields(ref_table_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_script ON script_dependencies(script_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_source ON script_dependencies(source_database_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_target ON script_dependencies(target_database_name)")
        
        self.conn.commit()
    
    def extract_all(self, database_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Extrahiert alle (oder ausgewählte) Datenbanken.
        
        Args:
            database_ids: Optional Liste von DB-IDs, sonst alle
            
        Returns:
            Statistiken über die Extraktion
        """
        import os

        # Integrity-Check VOR dem Öffnen: Prüfen ob existierende DB beschädigt ist
        if os.path.exists(self.db_path):
            try:
                test_conn = sqlite3.connect(self.db_path)
                test_cursor = test_conn.cursor()
                test_cursor.execute("PRAGMA integrity_check")
                result = test_cursor.fetchone()[0]
                test_conn.close()
                if result != 'ok':
                    raise sqlite3.DatabaseError(f"Integrity check failed: {result}")
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
                logger.warning(f"Beschädigte Datenbank erkannt: {e}")
                logger.warning("Datenbank wird gelöscht und neu erstellt...")
                try:
                    if self.conn:
                        self.conn.close()
                        self.conn = None
                except:
                    pass
                os.remove(self.db_path)

        if not self.conn:
            self.init_database()

        stats = {
            'databases': 0,
            'tables': 0,
            'fields': 0,
            'relationships': 0,
            'scripts': 0,
        }

        # Alte Daten löschen
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM scripts_fts")
        cursor.execute("DELETE FROM script_dependencies")
        cursor.execute("DELETE FROM scripts")
        cursor.execute("DELETE FROM relationships")
        cursor.execute("DELETE FROM fields")
        cursor.execute("DELETE FROM tables")
        cursor.execute("DELETE FROM databases")
        self.conn.commit()
        
        # Alle Datenbanken laden
        databases = self.api.get_databases()
        logger.info(f"Gefunden: {len(databases)} Datenbanken")
        
        for db_info in databases:
            db_id = db_info.get('id')
            db_name = db_info.get('name', db_id)
            
            # Filter wenn gewünscht
            if database_ids and db_id not in database_ids:
                continue
            
            logger.info(f"Extrahiere: {db_name} ({db_id})")
            
            try:
                db_stats = self._extract_database(db_id, db_name)
                stats['databases'] += 1
                stats['tables'] += db_stats['tables']
                stats['fields'] += db_stats['fields']
                stats['relationships'] += db_stats['relationships']
                stats['scripts'] += db_stats['scripts']
            except Exception as e:
                logger.error(f"Fehler bei {db_name}: {e}")
                continue
            
        self.conn.commit()
        return stats
    
    def _extract_database(self, db_id: str, db_name: str) -> Dict[str, int]:
        """Extrahiert eine einzelne Datenbank"""
        cursor = self.conn.cursor()
        stats = {'tables': 0, 'fields': 0, 'relationships': 0, 'scripts': 0}
        
        # Schema holen
        schema_data = self.api.get_database_schema(db_id)
        settings = schema_data.get('settings', {})
        schema = schema_data.get('schema', {})
        
        # Datenbank einfügen
        cursor.execute("""
            INSERT INTO databases (id, name, version, color, icon)
            VALUES (?, ?, ?, ?, ?)
        """, (
            db_id,
            settings.get('name', db_name),
            schema.get('version'),
            settings.get('color'),
            settings.get('icon')
        ))
        
        # Tabellen-Mapping für Referenz-Auflösung UND Code-Übersetzung
        table_id_to_name = {}
        table_uuid_to_name = {}
        field_maps = {}  # table_id → {field_id → field_caption}
        
        types = schema.get('types', {})
        for type_id, type_data in types.items():
            caption = type_data.get('caption', type_id)
            table_id_to_name[type_id] = caption
            if 'uuid' in type_data:
                table_uuid_to_name[type_data['uuid']] = caption
            
            # Feld-Mapping für diese Tabelle (für Statistiken)
            field_maps[type_id] = {}
            for field_id, field_data in type_data.get('fields', {}).items():
                field_caption = field_data.get('caption', field_id)
                field_maps[type_id][field_id] = field_caption

        # Team-Info vom API-Client
        team_id = self.api.team_id
        team_name = self.api.team_name

        def make_code_location(db_id, db_name, table_id, table_name, element_id, element_name,
                               code_type, category, code) -> CodeLocation:
            """Erstellt CodeLocation - Code kommt bereits formatiert von der API (formatScripts=T)"""
            return CodeLocation(
                team_id=team_id,
                team_name=team_name,
                database_id=db_id,
                database_name=db_name,
                table_id=table_id,
                table_name=table_name,
                element_id=element_id,
                element_name=element_name,
                code_type=code_type,
                code_category=category,
                code=code,
                code_original=None  # Nicht mehr benötigt da API bereits formatierten Code liefert
            )
        
        # Verknüpfungen sammeln
        all_relationships = set()
        all_scripts = []
        
        # Database-Level Code extrahieren
        for code_type, category in DATABASE_CODE_FIELDS.items():
            code = schema.get(code_type, '')
            if code and isinstance(code, str) and code.strip():
                all_scripts.append(make_code_location(
                    db_id, db_name, None, None, None, None,
                    code_type, category.value, code
                ))
        
        # Tabellen und Felder
        for type_id, type_data in types.items():
            table_name = type_data.get('caption', type_id)
            
            fields = type_data.get('fields', {})
            
            cursor.execute("""
                INSERT INTO tables (database_id, table_id, name, caption, icon, hidden, field_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                db_id,
                type_id,
                table_name,
                table_name,
                type_data.get('icon', ''),
                1 if type_data.get('hidden') else 0,
                len(fields)
            ))
            stats['tables'] += 1
            
            # Table-Level Code
            for code_type, category in TABLE_CODE_FIELDS.items():
                code = type_data.get(code_type, '')
                if code and isinstance(code, str) and code.strip():
                    all_scripts.append(make_code_location(
                        db_id, db_name, type_id, table_name, None, None,
                        code_type, category.value, code
                    ))
            
            # Felder extrahieren
            for field_id, field_data in fields.items():
                field_name = field_data.get('caption', field_id)
                base_type = field_data.get('base', '')
                
                # Referenz-Informationen
                ref_type_id = field_data.get('refTypeId')
                ref_type_uuid = field_data.get('refTypeUUID')
                ref_db_id = field_data.get('dbId')
                ref_db_name = field_data.get('dbName')
                is_composition = field_data.get('composition', False)
                
                # Ziel-Tabelle ermitteln
                ref_table_name = None
                if ref_type_id:
                    ref_table_name = table_id_to_name.get(ref_type_id, ref_type_id)
                elif ref_type_uuid:
                    ref_table_name = table_uuid_to_name.get(ref_type_uuid, ref_type_uuid)
                
                has_formula = 1 if field_data.get('fn') else 0
                
                cursor.execute("""
                    INSERT INTO fields (database_id, table_id, field_id, name, caption, 
                                       base_type, is_required, ref_table_id, ref_table_name,
                                       ref_database_id, is_composition, has_formula)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    db_id,
                    type_id,
                    field_id,
                    field_name,
                    field_name,
                    base_type,
                    1 if field_data.get('required') else 0,
                    ref_type_id,
                    ref_table_name,
                    ref_db_id,
                    1 if is_composition else 0,
                    has_formula
                ))
                stats['fields'] += 1
                
                # Verknüpfung erstellen
                if base_type == 'ref' and ref_table_name:
                    rel_type = "CROSS_DB" if ref_db_id else "N:1"
                    all_relationships.add(Relationship(
                        database_id=db_id,
                        database_name=db_name,
                        source_table_id=type_id,
                        source_table_name=table_name,
                        source_field_id=field_id,
                        source_field_name=field_name,
                        target_table_id=ref_type_id or '',
                        target_table_name=ref_table_name,
                        target_database_id=ref_db_id,
                        target_database_name=ref_db_name,
                        relationship_type=rel_type,
                        is_composition=is_composition
                    ))
                
                # Field-Level Code
                for code_type, category in FIELD_CODE_FIELDS.items():
                    code = field_data.get(code_type, '')
                    if code and isinstance(code, str) and code.strip():
                        # Skip sehr kurze Formeln
                        if code_type == 'fn' and len(code) < 3:
                            continue
                        
                        all_scripts.append(make_code_location(
                            db_id, db_name, type_id, table_name, field_id, field_name,
                            code_type, category.value, code
                        ))
        
        # Scripts speichern und Formel-Referenzen extrahieren
        for script in all_scripts:
            cursor.execute("""
                INSERT INTO scripts (team_id, team_name, database_id, database_name,
                                    table_id, table_name, element_id, element_name,
                                    code_type, code_category, code, code_original, line_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                script.team_id,
                script.team_name,
                script.database_id,
                script.database_name,
                script.table_id,
                script.table_name,
                script.element_id,
                script.element_name,
                script.code_type,
                script.code_category,
                script.code,
                script.code_original,
                script.line_count
            ))
            script_id = cursor.lastrowid
            stats['scripts'] += 1

            # Cross-Database-Referenzen extrahieren und speichern
            db_refs = self._extract_database_references(script.code)
            for ref in db_refs:
                cursor.execute("""
                    INSERT INTO script_dependencies
                    (script_id, source_database_id, source_database_name,
                     target_database_name, reference_type, code_snippet)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    script_id,
                    script.database_id,
                    script.database_name,
                    ref['target_database'],
                    ref['reference_type'],
                    ref['snippet']
                ))

            # Formel-Referenzen finden
            for ref_table in self._extract_formula_references(script.code, set(table_id_to_name.values())):
                all_relationships.add(Relationship(
                    database_id=db_id,
                    database_name=db_name,
                    source_table_id=script.table_id or '',
                    source_table_name=script.table_name or '(Database)',
                    source_field_id=script.element_id or '',
                    source_field_name=script.element_name or script.code_type,
                    target_table_id='',
                    target_table_name=ref_table,
                    relationship_type="FORMULA_REF",
                    found_in_code_type=script.code_type,
                    found_in_code=script.code[:500]
                ))
        
        # Verknüpfungen speichern
        for rel in all_relationships:
            cursor.execute("""
                INSERT INTO relationships (database_id, database_name, source_table_id,
                    source_table_name, source_field_id, source_field_name,
                    target_table_id, target_table_name, target_database_id,
                    target_database_name, relationship_type, is_composition,
                    reverse_field_name, found_in_code_type, found_in_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rel.database_id,
                rel.database_name,
                rel.source_table_id,
                rel.source_table_name,
                rel.source_field_id,
                rel.source_field_name,
                rel.target_table_id,
                rel.target_table_name,
                rel.target_database_id,
                rel.target_database_name,
                rel.relationship_type,
                1 if rel.is_composition else 0,
                rel.reverse_field_name,
                rel.found_in_code_type,
                rel.found_in_code
            ))
            stats['relationships'] += 1
        
        # Update table/code count
        cursor.execute("""
            UPDATE databases SET table_count = ?, code_count = ? WHERE id = ?
        """, (stats['tables'], stats['scripts'], db_id))
        
        return stats
    
    def _extract_formula_references(self, code: str, known_tables: Set[str]) -> Set[str]:
        """Extrahiert Tabellen-Referenzen aus Code"""
        references = set()
        
        for pattern, ref_type in self.TABLE_REFERENCE_PATTERNS:
            for match in re.finditer(pattern, code, re.IGNORECASE):
                table_name = match.group(1)
                
                # Nur bekannte Tabellen oder plausible Namen
                if table_name in known_tables or (
                    len(table_name) > 2 and 
                    table_name.lower() not in ('this', 'true', 'false', 'null', 'void', 'let', 'var', 'end', 'for', 'if', 'do', 'then', 'else')
                ):
                    references.add(table_name)
        
        return references

    def _extract_database_references(self, code: str) -> List[Dict[str, str]]:
        """
        Extrahiert Cross-Database-Referenzen aus Ninox-Code.

        Erkennt folgende Muster:
        - do as database 'Datenbankname' ... end
        - do as server ... end
        - openDatabase('Datenbankname')

        Returns:
            Liste von Dicts mit 'target_database', 'reference_type', 'snippet'
        """
        references = []

        # Pattern für "do as database 'Name'"
        db_pattern = r"do\s+as\s+database\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(db_pattern, code, re.IGNORECASE):
            target_db = match.group(1)
            start = max(0, match.start() - 20)
            end = min(len(code), match.end() + 50)
            snippet = code[start:end].replace('\n', ' ').strip()
            references.append({
                'target_database': target_db,
                'reference_type': 'do as database',
                'snippet': snippet
            })

        # Pattern für "do as server"
        server_pattern = r"do\s+as\s+server\b"
        for match in re.finditer(server_pattern, code, re.IGNORECASE):
            start = max(0, match.start() - 20)
            end = min(len(code), match.end() + 50)
            snippet = code[start:end].replace('\n', ' ').strip()
            references.append({
                'target_database': '(server)',
                'reference_type': 'do as server',
                'snippet': snippet
            })

        # Pattern für "openDatabase('Name')"
        open_pattern = r"openDatabase\s*\(\s*['\"]([^'\"]+)['\"]"
        for match in re.finditer(open_pattern, code, re.IGNORECASE):
            target_db = match.group(1)
            start = max(0, match.start() - 20)
            end = min(len(code), match.end() + 30)
            snippet = code[start:end].replace('\n', ' ').strip()
            references.append({
                'target_database': target_db,
                'reference_type': 'openDatabase',
                'snippet': snippet
            })

        return references

    # =========================================================================
    # Such-Funktionen
    # =========================================================================

    def search_scripts(
        self, 
        query: str, 
        database_id: Optional[str] = None,
        table_name: Optional[str] = None,
        code_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Volltextsuche in Scripts"""
        cursor = self.conn.cursor()
        
        # FTS5 Query
        sql = """
            SELECT 
                s.id, s.database_id, s.database_name, s.table_name, 
                s.element_name, s.code_type, s.code_category, s.code,
                s.line_count,
                highlight(scripts_fts, 0, '>>>', '<<<') as highlighted_code
            FROM scripts_fts 
            JOIN scripts s ON scripts_fts.rowid = s.id
            WHERE scripts_fts MATCH ?
        """
        params = [query]
        
        if database_id:
            sql += " AND s.database_id = ?"
            params.append(database_id)
        if table_name:
            sql += " AND s.table_name = ?"
            params.append(table_name)
        if code_type:
            sql += " AND s.code_type = ?"
            params.append(code_type)
            
        sql += f" ORDER BY rank LIMIT {limit}"
        
        try:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # Fallback auf LIKE-Suche
            return self.search_scripts_simple(query, limit)
    
    def search_scripts_simple(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Einfache LIKE-Suche"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM scripts 
            WHERE code LIKE ? OR table_name LIKE ? OR element_name LIKE ?
            ORDER BY database_name, table_name
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_relationships(
        self,
        database_id: Optional[str] = None,
        table_name: Optional[str] = None,
        relationship_type: Optional[str] = None,
        include_formula_refs: bool = True
    ) -> List[Dict[str, Any]]:
        """Gibt alle Verknüpfungen zurück"""
        cursor = self.conn.cursor()
        
        sql = "SELECT * FROM relationships WHERE 1=1"
        params = []
        
        if database_id:
            sql += " AND database_id = ?"
            params.append(database_id)
        if table_name:
            sql += " AND (source_table_name = ? OR target_table_name = ?)"
            params.extend([table_name, table_name])
        if relationship_type:
            sql += " AND relationship_type = ?"
            params.append(relationship_type)
        if not include_formula_refs:
            sql += " AND relationship_type != 'FORMULA_REF'"
            
        sql += " ORDER BY source_table_name, target_table_name"
        
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_table_dependencies(self, table_name: str) -> Dict[str, List[Dict]]:
        """Gibt alle Abhängigkeiten einer Tabelle zurück"""
        cursor = self.conn.cursor()
        
        # Referenziert
        cursor.execute("""
            SELECT * FROM relationships 
            WHERE source_table_name = ? AND relationship_type != 'FORMULA_REF'
        """, (table_name,))
        references = [dict(row) for row in cursor.fetchall()]
        
        # Wird referenziert von
        cursor.execute("""
            SELECT * FROM relationships 
            WHERE target_table_name = ? AND relationship_type != 'FORMULA_REF'
        """, (table_name,))
        referenced_by = [dict(row) for row in cursor.fetchall()]
        
        # Formel-Referenzen
        cursor.execute("""
            SELECT * FROM relationships 
            WHERE (source_table_name = ? OR target_table_name = ?) 
            AND relationship_type = 'FORMULA_REF'
        """, (table_name, table_name))
        formula_refs = [dict(row) for row in cursor.fetchall()]
        
        return {
            'references': references,
            'referenced_by': referenced_by,
            'formula_references': formula_refs
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Gibt Gesamtstatistiken zurück"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        for table in ['databases', 'tables', 'fields', 'relationships', 'scripts']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[f'{table}_count'] = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT code_type, COUNT(*) as count 
            FROM scripts GROUP BY code_type ORDER BY count DESC
        """)
        stats['scripts_by_type'] = {row['code_type']: row['count'] for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT relationship_type, COUNT(*) as count 
            FROM relationships GROUP BY relationship_type ORDER BY count DESC
        """)
        stats['relationships_by_type'] = {row['relationship_type']: row['count'] for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT table_name, COUNT(*) as count 
            FROM scripts WHERE table_name IS NOT NULL
            GROUP BY table_name ORDER BY count DESC LIMIT 10
        """)
        stats['top_tables_by_scripts'] = {row['table_name']: row['count'] for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT database_name, COUNT(*) as count 
            FROM scripts GROUP BY database_name ORDER BY count DESC
        """)
        stats['scripts_by_database'] = {row['database_name']: row['count'] for row in cursor.fetchall()}
        
        return stats
    
    def list_databases(self) -> List[Dict]:
        """Listet alle extrahierten Datenbanken"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM databases ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]
    
    def list_tables(self, database_id: Optional[str] = None) -> List[Dict]:
        """Listet alle Tabellen"""
        cursor = self.conn.cursor()
        if database_id:
            cursor.execute("SELECT * FROM tables WHERE database_id = ? ORDER BY name", (database_id,))
        else:
            cursor.execute("SELECT * FROM tables ORDER BY database_id, name")
        return [dict(row) for row in cursor.fetchall()]
    
    def export_to_json(self, output_path: str):
        """Exportiert alles als JSON"""
        cursor = self.conn.cursor()

        data = {
            'extracted_at': datetime.now().isoformat(),
            'databases': [],
        }

        cursor.execute("SELECT * FROM databases")
        for db_row in cursor.fetchall():
            db_data = dict(db_row)
            db_id = db_data['id']

            cursor.execute("SELECT * FROM tables WHERE database_id = ?", (db_id,))
            db_data['tables'] = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM fields WHERE database_id = ?", (db_id,))
            db_data['fields'] = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM relationships WHERE database_id = ?", (db_id,))
            db_data['relationships'] = [dict(row) for row in cursor.fetchall()]

            cursor.execute("SELECT * FROM scripts WHERE database_id = ?", (db_id,))
            db_data['scripts'] = [dict(row) for row in cursor.fetchall()]

            data['databases'].append(db_data)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def export_scripts_to_html(self, output_path: str, database_id: Optional[str] = None):
        """
        Exportiert alle Scripts als HTML mit Syntax-Highlighting.

        Args:
            output_path: Pfad zur HTML-Ausgabedatei
            database_id: Optional, nur Scripts dieser Datenbank exportieren
        """
        if not SYNTAX_HIGHLIGHTING_AVAILABLE:
            logger.error("Syntax-Highlighting nicht verfügbar - ninox_lexer.py fehlt")
            return

        cursor = self.conn.cursor()

        sql = "SELECT * FROM scripts"
        params = []
        if database_id:
            sql += " WHERE database_id = ?"
            params.append(database_id)
        sql += " ORDER BY database_name, table_name, code_type"

        cursor.execute(sql, params)
        scripts = cursor.fetchall()

        # HTML aufbauen
        html_parts = ['''<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ninox Scripts Export</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }
        .script-block {
            background: white;
            margin: 20px 0;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .script-header {
            background: #34495e;
            color: white;
            padding: 15px 20px;
            font-weight: 500;
        }
        .script-location {
            font-size: 18px;
            margin-bottom: 5px;
        }
        .script-meta {
            font-size: 14px;
            color: #bdc3c7;
        }
        .script-code {
            padding: 0;
            margin: 0;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            font-weight: 600;
            margin-right: 5px;
        }
        .badge-trigger { background: #e74c3c; color: white; }
        .badge-formula { background: #3498db; color: white; }
        .badge-button { background: #2ecc71; color: white; }
        .badge-permission { background: #f39c12; color: white; }
        .badge-global { background: #9b59b6; color: white; }
        .badge-other { background: #95a5a6; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Ninox Scripts Export</h1>
        <p>Extrahiert am: ''' + datetime.now().strftime('%d.%m.%Y %H:%M:%S') + f'''</p>
        <p>Anzahl Scripts: {len(scripts)}</p>
''']

        for script in scripts:
            script = dict(script)

            # Kategorie-Badge
            category = script.get('code_category', 'other')
            badge_class = f"badge-{category}"

            # Location
            location = f"{script['database_name']}"
            if script['table_name']:
                location += f" → {script['table_name']}"
            if script['element_name']:
                location += f" → {script['element_name']}"

            # Code highlighten
            code = script['code'] or ''
            highlighted_code = highlight_code(code, show_line_numbers=True)

            html_parts.append(f'''
        <div class="script-block">
            <div class="script-header">
                <div class="script-location">{location}</div>
                <div class="script-meta">
                    <span class="badge {badge_class}">{category}</span>
                    <span class="badge badge-other">{script['code_type']}</span>
                    <span style="margin-left: 10px;">Zeilen: {script['line_count']}</span>
                </div>
            </div>
            <div class="script-code">
                {highlighted_code}
            </div>
        </div>
''')

        html_parts.append('''
    </div>
</body>
</html>''')

        # HTML speichern
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(''.join(html_parts))

        logger.info(f"HTML Export erstellt: {output_path}")

    def export_to_markdown(self, output_path: str, database_id: Optional[str] = None):
        """
        Exportiert die Datenbankstruktur und alle Scripts als Markdown-Dokumentation.

        Args:
            output_path: Pfad zur Markdown-Ausgabedatei
            database_id: Optional - nur diese Datenbank exportieren
        """
        from datetime import datetime

        # Daten aus DB laden
        cur = self.conn.cursor()

        # Datenbanken laden
        if database_id:
            cur.execute("SELECT * FROM databases WHERE id = ? OR name = ?", (database_id, database_id))
        else:
            cur.execute("SELECT * FROM databases ORDER BY name")
        databases = cur.fetchall()

        lines = []
        lines.append("# 📚 Ninox Dokumentation")
        lines.append("")
        lines.append(f"> Generiert am: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        lines.append("> Diese Datei enthält die vollständige Struktur und alle Skripte.")
        lines.append("")

        # Inhaltsverzeichnis
        lines.append("## Inhaltsverzeichnis")
        lines.append("")
        for db in databases:
            db_name = db['name']
            anchor = db_name.lower().replace(' ', '-').replace('.', '')
            lines.append(f"- [{db_name}](#{anchor})")
        lines.append("")

        # Pro Datenbank
        for db in databases:
            db_name = db['name']
            db_id = db['id']

            lines.append("---")
            lines.append(f"## 📁 {db_name}")
            lines.append("")
            lines.append(f"- **ID:** `{db_id}`")
            lines.append(f"- **Tabellen:** {db['table_count']}")
            lines.append(f"- **Scripts:** {db['code_count']}")
            lines.append("")

            # Tabellen dieser DB
            cur.execute("""
                SELECT * FROM tables WHERE database_id = ? ORDER BY name
            """, (db_id,))
            tables = cur.fetchall()

            for table in tables:
                table_name = table['name']
                caption = table['caption'] or table_name
                table_id = table['table_id']

                lines.append(f"### 📂 {caption}")
                if caption != table_name:
                    lines.append(f"*ID: `{table_id}` | Name: `{table_name}`*")
                else:
                    lines.append(f"*ID: `{table_id}`*")
                lines.append("")

                # Felder dieser Tabelle
                cur.execute("""
                    SELECT * FROM fields
                    WHERE database_id = ? AND table_id = ?
                    ORDER BY name
                """, (db_id, table_id))
                fields = cur.fetchall()

                if fields:
                    lines.append("#### Felder")
                    lines.append("")
                    lines.append("| Feldname | ID | Typ | Info |")
                    lines.append("|----------|-----|-----|------|")

                    for field in fields:
                        f_name = field['caption'] or field['name']
                        f_id = field['field_id']
                        f_type = field['base_type']
                        f_ref = field['ref_table_name'] or ""
                        if f_ref:
                            f_ref = f"→ `{f_ref}`"

                        lines.append(f"| **{f_name}** | `{f_id}` | {f_type} | {f_ref} |")

                    lines.append("")

                # Scripts dieser Tabelle
                cur.execute("""
                    SELECT * FROM scripts
                    WHERE database_id = ? AND table_name = ?
                    ORDER BY element_name, code_type
                """, (db_id, table_name))
                scripts = cur.fetchall()

                if scripts:
                    lines.append("#### 📜 Skripte")
                    lines.append("")

                    for script in scripts:
                        element = script['element_name'] or "(Tabellen-Ebene)"
                        code_type = script['code_type']
                        category = script['code_category']
                        code = script['code'] or ""

                        # Code bereinigen
                        code = code.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')

                        lines.append(f"**{element}** - `{code_type}` ({category})")
                        lines.append("")
                        lines.append("```javascript")
                        lines.append(code.strip())
                        lines.append("```")
                        lines.append("")

            # Globale Scripts (ohne Tabelle)
            cur.execute("""
                SELECT * FROM scripts
                WHERE database_id = ? AND (table_name IS NULL OR table_name = '')
                ORDER BY code_type
            """, (db_id,))
            global_scripts = cur.fetchall()

            if global_scripts:
                lines.append("### 🌐 Globale Funktionen")
                lines.append("")

                for script in global_scripts:
                    code_type = script['code_type']
                    code = script['code'] or ""
                    code = code.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\t', '\t')

                    lines.append(f"**{code_type}**")
                    lines.append("")
                    lines.append("```javascript")
                    lines.append(code.strip())
                    lines.append("```")
                    lines.append("")

        # Beziehungen
        cur.execute("""
            SELECT DISTINCT database_name FROM relationships ORDER BY database_name
        """)
        rel_dbs = cur.fetchall()

        if rel_dbs:
            lines.append("---")
            lines.append("## 🔗 Beziehungen")
            lines.append("")

            for rel_db in rel_dbs:
                db_name = rel_db['database_name']
                lines.append(f"### {db_name}")
                lines.append("")
                lines.append("| Von | Nach | Typ | Feld |")
                lines.append("|-----|------|-----|------|")

                cur.execute("""
                    SELECT * FROM relationships WHERE database_name = ?
                    ORDER BY source_table_name
                """, (db_name,))
                rels = cur.fetchall()

                for rel in rels:
                    lines.append(f"| {rel['source_table_name']} | {rel['target_table_name']} | {rel['relationship_type']} | {rel['source_field_name'] or '-'} |")

                lines.append("")

        # Markdown speichern
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Markdown Export erstellt: {output_path}")

    def close(self):
        """Schließt die Verbindung"""
        if self.conn:
            self.conn.close()
            self.conn = None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ninox API Schema & Script Extractor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  # Extraktion von API
  python ninox_api_extractor.py extract --domain https://ninox.example.com \\
                                        --team TEAM_ID --apikey API_KEY

  # Mit Config-Datei
  python ninox_api_extractor.py extract --config config.yaml --env dev

  # Suchen
  python ninox_api_extractor.py search "select Kunden" --db ninox_schema.db
  python ninox_api_extractor.py search "http(" --type onClick

  # Abhängigkeiten
  python ninox_api_extractor.py deps "Aufträge" --db ninox_schema.db

  # Statistiken
  python ninox_api_extractor.py stats --db ninox_schema.db

  # JSON Export
  python ninox_api_extractor.py export output.json --db ninox_schema.db

  # HTML Export mit Syntax-Highlighting
  python ninox_api_extractor.py html scripts.html --db ninox_schema.db
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Befehle')
    
    # Extract
    extract_p = subparsers.add_parser('extract', help='Extrahiert von der API')
    extract_p.add_argument('--domain', help='Ninox Domain (z.B. https://app.ninox.com)')
    extract_p.add_argument('--team', help='Team/Workspace ID')
    extract_p.add_argument('--apikey', help='API Key')
    extract_p.add_argument('--config', help='Config YAML Datei')
    extract_p.add_argument('--env', default='dev', help='Environment in Config')
    extract_p.add_argument('--db', default='ninox_schema.db', help='SQLite Ausgabe')
    extract_p.add_argument('--databases', nargs='*', help='Nur bestimmte DB-IDs')
    
    # Search
    search_p = subparsers.add_parser('search', help='Sucht in Scripts')
    search_p.add_argument('query', help='Suchbegriff')
    search_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    search_p.add_argument('--table', help='Filter auf Tabelle')
    search_p.add_argument('--type', help='Filter auf Code-Typ')
    search_p.add_argument('--limit', type=int, default=20, help='Max Ergebnisse')
    search_p.add_argument('--show-code', action='store_true', help='Vollständigen Code anzeigen')
    
    # Deps
    deps_p = subparsers.add_parser('deps', help='Zeigt Abhängigkeiten')
    deps_p.add_argument('table', help='Tabellenname')
    deps_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    
    # Stats
    stats_p = subparsers.add_parser('stats', help='Zeigt Statistiken')
    stats_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    
    # List
    list_p = subparsers.add_parser('list', help='Listet Datenbanken/Tabellen')
    list_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    list_p.add_argument('--database', help='Filter auf Datenbank')
    
    # Export
    export_p = subparsers.add_parser('export', help='JSON Export')
    export_p.add_argument('output', help='Ausgabedatei')
    export_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')

    # HTML Export
    html_p = subparsers.add_parser('html', help='HTML Export mit Syntax-Highlighting')
    html_p.add_argument('output', help='HTML Ausgabedatei')
    html_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    html_p.add_argument('--database', help='Nur diese Datenbank exportieren')

    # Markdown Export
    md_p = subparsers.add_parser('md', help='Markdown Dokumentation generieren')
    md_p.add_argument('output', help='Markdown Ausgabedatei (.md)')
    md_p.add_argument('--db', default='ninox_schema.db', help='SQLite DB')
    md_p.add_argument('--database', help='Nur diese Datenbank exportieren')

    args = parser.parse_args()
    
    if args.command == 'extract':
        # Credentials laden (Priorität: CLI-Argumente > Config-Datei > Umgebungsvariablen)
        domain = args.domain
        team_id = args.team
        team_name = None
        api_key = args.apikey

        if args.config:
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f)
            env_config = config.get('environments', {}).get(args.env, {})
            domain = domain or env_config.get('domain')
            team_id = team_id or env_config.get('workspaceId') or env_config.get('teamId')
            team_name = env_config.get('teamName') or env_config.get('name') or args.env
            api_key = api_key or env_config.get('apiKey')

        # Fallback auf Umgebungsvariablen (aus .env oder System)
        domain = domain or os.getenv('NINOX_DOMAIN')
        team_id = team_id or os.getenv('NINOX_TEAM_ID')
        team_name = team_name or os.getenv('NINOX_TEAM_NAME') or team_id
        api_key = api_key or os.getenv('NINOX_API_KEY')

        if not all([domain, team_id, api_key]):
            print("❌ Fehler: domain, team und apikey müssen angegeben werden!")
            return

        print(f"🔌 Verbinde mit: {domain}")

        # Client erstellen und Team-Namen von API holen wenn nicht in Config
        client = NinoxAPIClient(domain, team_id, api_key, team_name=team_name)
        if not team_name or team_name == team_id:
            api_team_name = client.get_team_name()
            client.team_name = api_team_name
            print(f"📦 Team: {api_team_name} ({team_id})")
        else:
            print(f"📦 Team: {team_name} ({team_id})")

        extractor = NinoxSchemaExtractor(client, args.db)

        stats = extractor.extract_all(args.databases)
        
        print(f"\n✅ Extraktion abgeschlossen:")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        print(f"\n💾 Gespeichert in: {args.db}")
        extractor.close()
        
    elif args.command == 'search':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row

        results = extractor.search_scripts(
            args.query,
            table_name=args.table,
            code_type=args.type,
            limit=args.limit
        )

        print(f"\n🔍 {len(results)} Treffer für '{args.query}':\n")
        for i, r in enumerate(results, 1):
            loc = f"{r['database_name']}.{r['table_name'] or '(DB)'}"
            if r['element_name']:
                loc += f".{r['element_name']}"
            print(f"📍 {i}. {loc}")
            print(f"   Typ: {r['code_type']} ({r['code_category']}) | Zeilen: {r['line_count']}")

            if args.show_code:
                # Vollständigen Code anzeigen
                print(f"\n{'─' * 80}")
                code_lines = r['code'].split('\n')
                for line_num, line in enumerate(code_lines, 1):
                    print(f"   {line_num:4d} | {line}")
                print(f"{'─' * 80}\n")
            else:
                # Nur Preview
                if SYNTAX_HIGHLIGHTING_AVAILABLE:
                    code_preview = get_code_preview(r['code'], max_length=150)
                else:
                    code_preview = r['code'][:150].replace('\n', ' ↵ ')
                print(f"   {code_preview}...")
            print()
        extractor.close()
        
    elif args.command == 'deps':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row
        
        deps = extractor.get_table_dependencies(args.table)
        
        print(f"\n📊 Abhängigkeiten für '{args.table}':\n")
        
        print("→ Referenziert (N:1):")
        for ref in deps['references']:
            comp = " [Composition]" if ref['is_composition'] else ""
            print(f"   {ref['source_field_name']} → {ref['target_table_name']}{comp}")
        if not deps['references']:
            print("   (keine)")
        
        print("\n← Wird referenziert von (1:N):")
        for ref in deps['referenced_by']:
            print(f"   {ref['source_table_name']}.{ref['source_field_name']}")
        if not deps['referenced_by']:
            print("   (keine)")
            
        print(f"\n📝 Formel-Referenzen: {len(deps['formula_references'])}")
        for ref in deps['formula_references'][:5]:
            print(f"   {ref['source_table_name']}.{ref['source_field_name']} ({ref['found_in_code_type']})")
        extractor.close()
        
    elif args.command == 'stats':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row
        
        stats = extractor.get_statistics()
        
        print("\n📊 Ninox Schema Statistiken:\n")
        print(f"   Datenbanken:   {stats['databases_count']}")
        print(f"   Tabellen:      {stats['tables_count']}")
        print(f"   Felder:        {stats['fields_count']}")
        print(f"   Verknüpfungen: {stats['relationships_count']}")
        print(f"   Scripts:       {stats['scripts_count']}")
        
        print("\n📝 Scripts nach Typ:")
        for typ, count in list(stats['scripts_by_type'].items())[:10]:
            print(f"   {typ}: {count}")
            
        print("\n🔗 Verknüpfungen nach Typ:")
        for typ, count in stats['relationships_by_type'].items():
            print(f"   {typ}: {count}")
            
        print("\n🏆 Top Tabellen (nach Scripts):")
        for table, count in list(stats['top_tables_by_scripts'].items())[:5]:
            print(f"   {table}: {count}")
        extractor.close()
        
    elif args.command == 'list':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row
        
        if args.database:
            tables = extractor.list_tables(args.database)
            print(f"\n📋 Tabellen in {args.database}:\n")
            for t in tables:
                print(f"   {t['name']} ({t['field_count']} Felder)")
        else:
            dbs = extractor.list_databases()
            print(f"\n📋 Datenbanken ({len(dbs)}):\n")
            for db in dbs:
                print(f"   {db['name']} ({db['id']})")
                print(f"      Tabellen: {db['table_count']}, Scripts: {db['code_count']}")
        extractor.close()
        
    elif args.command == 'export':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row

        extractor.export_to_json(args.output)
        print(f"✅ Exportiert: {args.output}")
        extractor.close()

    elif args.command == 'html':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row

        extractor.export_scripts_to_html(args.output, args.database)
        print(f"✅ HTML exportiert: {args.output}")
        extractor.close()

    elif args.command == 'md':
        extractor = NinoxSchemaExtractor(None, args.db)
        extractor.conn = sqlite3.connect(args.db)
        extractor.conn.row_factory = sqlite3.Row

        extractor.export_to_markdown(args.output, args.database)
        print(f"✅ Markdown exportiert: {args.output}")
        extractor.close()

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
