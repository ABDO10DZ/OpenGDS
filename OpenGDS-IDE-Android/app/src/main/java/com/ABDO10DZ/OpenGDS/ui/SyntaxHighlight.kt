package com.ABDO10DZ.OpenGDS.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation

@Composable
fun syntaxTransformation(
    language: String,
    searchTerm: String = "",
    searchRegex: Boolean = false,
    activeSearchRange: TextRange? = null
): VisualTransformation {
    val colors = MaterialTheme.colorScheme
    val keyword = Color(0xFFC792EA)
    val string = Color(0xFFA5D6A7)
    val number = Color(0xFFFFCB6B)
    val comment = colors.onSurfaceVariant.copy(alpha = 0.72f)
    val annotation = Color(0xFF82AAFF)
    val directive = Color(0xFFFF9E80)
    val type = Color(0xFF80CBC4)
    val function = Color(0xFF82AAFF)
    val literal = Color(0xFFFFD580)

    val smaliPatterns = listOf(
        Regex("(?m)#.*$") to comment,
        Regex("\"(?:\\\\.|[^\"\\\\])*\"|'(?:\\\\.|[^'\\\\])*'") to string,
        Regex("\\.([A-Za-z][A-Za-z0-9_-]*)") to directive,
        Regex("\\b(?:invoke-[A-Za-z/-]+|move(?:-result(?:-object|-wide)?|-exception)?|const(?:/\\w+)?|return(?:-void)?|if-[A-Za-z-]+|goto(?:/\\w+)?|new-instance|new-array|sget(?:-object)?|sput(?:-object)?|iget(?:-object)?|iput(?:-object)?|check-cast|instance-of|throw|monitor-[A-Za-z]+|packed-switch|sparse-switch|fill-array-data)\\b") to keyword,
        Regex("\\b(?:v|p)\\d+\\b") to annotation,
        Regex("\\b(?:0x[0-9a-fA-F]+|\\d+)\\b") to number
    )

    return remember(
        language, searchTerm, searchRegex, activeSearchRange,
        keyword, string, number, comment, annotation, directive, type, function, literal
    ) {
        VisualTransformation { source ->
            // Keep syntax highlighting enabled for large project scripts too.
            // The previous 20k-character shortcut silently rendered long .gd files as plain text.
            // The scanner below is linear and does not change source offsets or editor contents.
            val builder = AnnotatedString.Builder(source)
            when (language) {
                "gd" -> highlightGdscript(
                    builder = builder,
                    text = source.text,
                    keyword = keyword,
                    string = string,
                    number = number,
                    comment = comment,
                    annotation = annotation,
                    directive = directive,
                    type = type,
                    function = function,
                    literal = literal
                )
                "smali" -> smaliPatterns.forEach { (pattern, color) ->
                    pattern.findAll(source.text).forEach { match ->
                        builder.addStyle(SpanStyle(color = color), match.range.first, match.range.last + 1)
                    }
                }
            }

            // Search highlighting is applied last so it remains visible over syntax colors.
            if (searchTerm.isNotBlank()) {
                val pattern = runCatching {
                    if (searchRegex) Regex(searchTerm, RegexOption.IGNORE_CASE)
                    else Regex(Regex.escape(searchTerm), RegexOption.IGNORE_CASE)
                }.getOrNull()
                pattern?.findAll(source.text)?.forEach { match ->
                    val isActive = activeSearchRange != null &&
                        activeSearchRange.start == match.range.first &&
                        activeSearchRange.end == match.range.last + 1
                    val background = if (isActive) Color(0xFFFFB74D).copy(alpha = 0.72f)
                        else Color(0xFFFFD76A).copy(alpha = 0.28f)
                    builder.addStyle(SpanStyle(background = background), match.range.first, match.range.last + 1)
                }
            }
            TransformedText(builder.toAnnotatedString(), OffsetMapping.Identity)
        }
    }
}

private fun highlightGdscript(
    builder: AnnotatedString.Builder,
    text: String,
    keyword: Color,
    string: Color,
    number: Color,
    comment: Color,
    annotation: Color,
    directive: Color,
    type: Color,
    function: Color,
    literal: Color
) {
    val keywords = setOf(
        "and", "as", "assert", "await", "break", "breakpoint", "class", "class_name",
        "const", "continue", "elif", "else", "enum", "extends", "for", "func", "get",
        "if", "in", "is", "lambda", "match", "namespace", "not", "or", "pass",
        "preload", "return", "self", "set", "signal", "static", "super", "var", "void",
        "when", "while"
    )
    val literals = setOf("true", "false", "null")
    val constants = setOf("PI", "TAU", "INF", "NAN", "NAN", "OK", "FAILED")
    val types = setOf(
        "Variant", "bool", "int", "float", "String", "StringName", "NodePath", "Array",
        "Dictionary", "Callable", "Signal", "Object", "RefCounted", "Resource", "WeakRef",
        "Node", "Node2D", "Node3D", "Control", "CanvasItem", "SceneTree", "Viewport",
        "PackedByteArray", "PackedInt32Array", "PackedInt64Array", "PackedFloat32Array",
        "PackedFloat64Array", "PackedStringArray", "PackedVector2Array", "PackedVector3Array",
        "PackedColorArray", "Vector2", "Vector2i", "Vector3", "Vector3i", "Vector4",
        "Vector4i", "Rect2", "Rect2i", "Transform2D", "Transform3D", "Basis", "Quaternion",
        "AABB", "Color", "Plane", "Projection", "RID", "Callable", "Error"
    )
    val functions = setOf(
        "print", "print_rich", "prints", "printt", "printerr", "push_error", "push_warning",
        "assert", "is_instance_valid", "len", "range", "load", "str", "type_string", "typeof",
        "var_to_str", "str_to_var", "hash", "weakref", "convert", "clamp", "min", "max",
        "abs", "sign", "snapped", "lerp", "inverse_lerp", "remap", "smoothstep", "move_toward",
        "wrap", "wrapf", "posmod", "fposmod", "floor", "ceil", "round", "sqrt", "pow",
        "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "deg_to_rad", "rad_to_deg",
        "randf", "randi", "randf_range", "randi_range", "seed", "rand_from_seed", "preload"
    )

    fun isIdentifierStart(char: Char): Boolean = char == '_' || char.isLetter()
    fun isIdentifierPart(char: Char): Boolean = char == '_' || char.isLetterOrDigit()
    fun paint(start: Int, endExclusive: Int, color: Color) {
        if (start >= 0 && endExclusive > start && endExclusive <= text.length) {
            builder.addStyle(SpanStyle(color = color), start, endExclusive)
        }
    }

    var index = 0
    while (index < text.length) {
        val current = text[index]

        // GDScript line comments begin with #; keep their contents out of token parsing.
        if (current == '#') {
            val start = index
            while (index < text.length && text[index] != '\n') index++
            paint(start, index, comment)
            continue
        }

        // Single-line and triple-quoted strings, with escaped delimiters.
        if (current == '"' || current == '\'') {
            val start = index
            val triple = current == '"' && text.startsWith("\"\"\"", index)
            val delimiterLength = if (triple) 3 else 1
            index += delimiterLength
            var escaped = false
            while (index < text.length) {
                if (triple && text.startsWith("\"\"\"", index) && !escaped) {
                    index += 3
                    break
                }
                val char = text[index]
                if (!triple && char == current && !escaped) {
                    index++
                    break
                }
                if (char == '\\' && !escaped) escaped = true else escaped = false
                index++
            }
            paint(start, index, string)
            continue
        }

        // Annotations such as @export, @onready and @tool.
        if (current == '@' && text.getOrNull(index + 1)?.let { it == '_' || it.isLetter() } == true) {
            val start = index++
            while (index < text.length && isIdentifierPart(text[index])) index++
            paint(start, index, annotation)
            continue
        }

        if (isIdentifierStart(current)) {
            val start = index++
            while (index < text.length && isIdentifierPart(text[index])) index++
            val token = text.substring(start, index)
            val color = when {
                token in keywords -> keyword
                token in literals -> literal
                token in constants -> directive
                token in types -> type
                token in functions -> function
                else -> null
            }
            if (color != null) paint(start, index, color)
            continue
        }

        if (current.isDigit() || (current == '.' && text.getOrNull(index + 1)?.isDigit() == true)) {
            val start = index++
            while (index < text.length) {
                val char = text[index]
                val previous = text[index - 1]
                if (char.isLetterOrDigit() || char == '_' || char == '.' ||
                    ((char == '+' || char == '-') && (previous == 'e' || previous == 'E'))
                ) index++ else break
            }
            paint(start, index, number)
            continue
        }

        index++
    }
}
