package com.ABDO10DZ.OpenGDS.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.text.input.InputTransformation
import androidx.compose.ui.text.TextRange
import androidx.compose.foundation.text.input.delete
import androidx.compose.foundation.text.input.insert

/**
 * GDScript delimiter assistance for the state-based BasicTextField API.
 * Only single-character edits are transformed; paste, IME composition and selections are left alone.
 */
@OptIn(ExperimentalFoundationApi::class)
internal fun gdAutoPairInputTransformation(): InputTransformation = InputTransformation {
    if (!originalSelection.collapsed || !selection.collapsed) return@InputTransformation

    val oldText = originalText.toString()
    val newText = toString()
    val oldCursor = originalSelection.end
    val newCursor = selection.end
    val changeList = changes
    if (changeList.changeCount != 1) return@InputTransformation

    val newRange = changeList.getRange(0)
    val oldRange = changeList.getOriginalRange(0)
    val pairs = mapOf('(' to ')', '[' to ']', '{' to '}', '"' to '"', '\'' to '\'')
    val closingSymbols = pairs.values.toSet()

    // Typing an existing closing character moves over it instead of duplicating it.
    if (newRange.length == 1 && oldRange.collapsed && oldRange.start == oldCursor &&
        newCursor == oldCursor + 1 &&
        newText.removeRange(newRange.start, newRange.end) == oldText
    ) {
        val typed = newText.getOrNull(newRange.start)
        if (typed != null && typed in closingSymbols && oldText.getOrNull(oldCursor) == typed) {
            delete(newRange.start, newRange.end)
            selection = TextRange((oldCursor + 1).coerceIn(0, length))
            return@InputTransformation
        }

        // Insert the matching closer and leave the caret between the pair.
        val closing = typed?.let(pairs::get)
        if (closing != null && newRange.start == oldCursor && newRange.end == newCursor &&
            newText.getOrNull(newRange.end) != closing
        ) {
            insert(newRange.end, closing.toString())
            selection = TextRange(newRange.end)
            return@InputTransformation
        }
    }

    // Backspace between an empty pair removes both delimiters.
    if (newRange.collapsed && oldRange.length == 1 &&
        oldRange.start == oldCursor - 1 && newCursor == oldCursor - 1 &&
        newText == oldText.removeRange(oldRange.start, oldRange.end)
    ) {
        val opener = oldText.getOrNull(oldRange.start)
        val closer = opener?.let(pairs::get)
        if (closer != null && oldText.getOrNull(oldCursor) == closer &&
            newText.getOrNull(newRange.start) == closer
        ) {
            delete(newRange.start, (newRange.start + 1).coerceAtMost(length))
            selection = TextRange(newRange.start.coerceIn(0, length))
        }
    }
}
