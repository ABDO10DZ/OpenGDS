"""GDScript source editor widget with syntax coloring and breakpoint gutter."""
from __future__ import annotations
import re
from PySide6.QtCore import Qt, QRect, QSize, QStringListModel, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextFormat, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QCompleter, QTextEdit


class GDScriptHighlighter(QSyntaxHighlighter):
    def __init__(self, document, theme="dark"):
        super().__init__(document)
        self.theme = theme
        self._build()

    def _fmt(self, color, bold=False, italic=False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _build(self):
        dark = self.theme != "light"
        self.rules = [
            (r'\b(func|var|const|class|class_name|extends|static|signal|enum|return|if|elif|else|for|while|match|when|break|continue|pass|await|as|is|in|not|and|or|self|super|preload|assert|breakpoint)\b', self._fmt("#c586c0" if dark else "#8b3fa0", True)),
            (r'\b(true|false|null|PI|TAU|INF|NAN)\b', self._fmt("#569cd6" if dark else "#0451a5")),
            (r'\b[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\b', self._fmt("#b5cea8" if dark else "#098658")),
            (r'@[A-Za-z_][A-Za-z0-9_]*', self._fmt("#dcdcaa" if dark else "#795e26")),
            (r'\b[A-Z][A-Z0-9_]*\b', self._fmt("#4ec9b0" if dark else "#267f99")),
            (r'#[^\n]*', self._fmt("#6a9955" if dark else "#008000", False, True)),
            (r'"([^"\\]|\\.)*"|\'([^\'\\]|\\.)*\'|"""[\s\S]*?"""', self._fmt("#ce9178" if dark else "#a31515")),
            (r'\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()', self._fmt("#dcdcaa" if dark else "#795e26")),
        ]

    def set_theme(self, theme):
        self.theme = theme
        self._build()
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.editor.toggle_breakpoint_at_y(event.position().toPoint().y())


class CodeEditor(QPlainTextEdit):
    PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
    breakpointsChanged = Signal(object)
    completionRequested = Signal(int, int)

    def __init__(self, theme="dark", tab_width=4, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.tab_width = int(tab_width)
        self.breakpoints: set[int] = set()
        self._completion_insertions: dict[str, str] = {}
        self.auto_pairs = True
        self.auto_indent = True
        self.auto_completion = True
        self.line_numbers_visible = True
        self.line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_width)
        self.updateRequest.connect(self.update_line_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_width(0)
        self.highlighter = GDScriptHighlighter(self.document(), theme)
        self.setFont(QFont("Consolas", 11))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.tab_width)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlight_current_line()
        words = "func var const class class_name extends static signal enum return if elif else for while match when break continue pass await as is in not and or self super preload assert breakpoint print range len str int float bool Array Dictionary Node Node2D CharacterBody2D Control Vector2 Vector3 Color Input OS Engine get_node get_tree queue_free _ready _process _physics_process".split()
        self.completion_model = QStringListModel(words, self)
        self.completer = QCompleter(self.completion_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.activated.connect(self.insert_completion)

    def line_number_width(self):
        return 20 + self.fontMetrics().horizontalAdvance("9") * (len(str(max(1, self.blockCount()))) + 1)

    def update_line_width(self, _):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def update_line_area(self, rect, dy):
        if dy:
            self.line_area.scroll(0, dy)
        else:
            self.line_area.update(0, rect.y(), self.line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_area)
        painter.fillRect(event.rect(), QColor("#252526" if self.theme != "light" else "#f3f3f3"))
        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if number in self.breakpoints:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#e51400"))
                    painter.drawEllipse(3, top + 3, 9, 9)
                painter.setPen(QColor("#858585" if self.theme != "light" else "#777777"))
                painter.drawText(15, top, self.line_area.width() - 20, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(number))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1

    def toggle_breakpoint_at_y(self, y):
        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid():
            if block.isVisible() and top <= y <= bottom:
                self.toggle_breakpoint(block.blockNumber() + 1)
                return
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())

    def toggle_breakpoint(self, line=None):
        line = int(line if line is not None else self.textCursor().blockNumber() + 1)
        if line in self.breakpoints:
            self.breakpoints.remove(line)
        else:
            self.breakpoints.add(line)
        self.breakpointsChanged.emit(sorted(self.breakpoints))
        self.line_area.update()

    def set_breakpoints(self, lines):
        self.breakpoints = {int(line) for line in lines if int(line) > 0}
        self.line_area.update()
        self.breakpointsChanged.emit(sorted(self.breakpoints))

    def highlight_current_line(self):
        selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#2a2d2e" if self.theme != "light" else "#eef6fc"))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)

    def set_theme(self, theme):
        self.theme = theme
        self.highlighter.set_theme(theme)
        self.highlight_current_line()
        self.line_area.update()

    def configure_features(self, *, auto_pairs=None, auto_indent=None, auto_completion=None, line_numbers=None, word_wrap=None):
        if auto_pairs is not None:
            self.auto_pairs = bool(auto_pairs)
        if auto_indent is not None:
            self.auto_indent = bool(auto_indent)
        if auto_completion is not None:
            self.auto_completion = bool(auto_completion)
        if line_numbers is not None:
            self.line_numbers_visible = bool(line_numbers)
            self.line_area.setVisible(self.line_numbers_visible)
            self.setViewportMargins(self.line_number_width() if self.line_numbers_visible else 0, 0, 0, 0)
        if word_wrap is not None:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if word_wrap else QPlainTextEdit.LineWrapMode.NoWrap)

    def set_completions(self, words, insertions=None):
        unique = sorted({str(word) for word in words if str(word)}, key=str.casefold)
        self.completion_model.setStringList(unique)
        self._completion_insertions = dict(insertions or {})

    def insert_completion(self, completion):
        tc = self.textCursor()
        prefix = self.completer.completionPrefix()
        tc.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, len(prefix))
        tc.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, len(prefix))
        tc.insertText(self._completion_insertions.get(str(completion), str(completion)))
        self.setTextCursor(tc)

    def keyPressEvent(self, event):
        tc = self.textCursor()
        ch = event.text()
        if event.key() == Qt.Key.Key_F9:
            self.toggle_breakpoint()
            return
        if event.key() == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.auto_completion:
                self.completionRequested.emit(tc.blockNumber(), tc.positionInBlock())
                self.completer.complete(self.cursorRect())
            return
        if event.key() == Qt.Key.Key_Tab and not self.completer.popup().isVisible():
            tc.insertText(" " * self.tab_width)
            return
        if self.auto_pairs and ch in self.PAIRS.values() and not tc.hasSelection():
            text = self.toPlainText()
            if tc.position() < len(text) and text[tc.position()] == ch:
                tc.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(tc)
                return
        if self.auto_pairs and ch in self.PAIRS and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            close = self.PAIRS[ch]
            if ch in ('"', "'") and tc.hasSelection():
                selected = tc.selectedText()
                tc.insertText(ch + selected + close)
                self.setTextCursor(tc)
                return
            tc.insertText(ch + close)
            tc.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(tc)
            return
        if event.key() == Qt.Key.Key_Backspace and not tc.hasSelection():
            pos = tc.position()
            text = self.toPlainText()
            if self.auto_pairs and pos < len(text) and pos > 0 and text[pos - 1] in self.PAIRS and text[pos] == self.PAIRS[text[pos - 1]]:
                tc.deletePreviousChar()
                tc.deleteChar()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.completer.popup().isVisible() and self.auto_indent:
            block = tc.block().text()
            indent = len(block) - len(block.lstrip(" "))
            if block.strip().endswith(":"):
                indent += self.tab_width
            super().keyPressEvent(event)
            self.textCursor().insertText(" " * indent)
            return
        super().keyPressEvent(event)
        if self.auto_completion and ch and (ch.isalnum() or ch == "_") and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            tc = self.textCursor()
            tc.select(QTextCursor.SelectionType.WordUnderCursor)
            prefix = tc.selectedText()
            if len(prefix) >= 2:
                self.completer.setCompletionPrefix(prefix)
                rect = self.cursorRect()
                rect.setWidth(self.completer.popup().sizeHintForColumn(0) + self.completer.popup().verticalScrollBar().sizeHint().width())
                self.completer.complete(rect)
        elif self.completer.popup().isVisible():
            self.completer.popup().hide()
