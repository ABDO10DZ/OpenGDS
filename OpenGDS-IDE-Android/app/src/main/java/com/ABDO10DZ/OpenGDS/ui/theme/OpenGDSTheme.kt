package com.ABDO10DZ.OpenGDS.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Ink = Color(0xFF11121B)
private val Panel = Color(0xFF1A1C29)
private val Violet = Color(0xFF8B7CFF)
private val Mint = Color(0xFF4DD6B2)
private val DarkScheme = darkColorScheme(
    primary = Violet,
    secondary = Mint,
    background = Ink,
    surface = Panel,
    surfaceVariant = Color(0xFF272A3A),
    onPrimary = Color.White,
    onBackground = Color(0xFFF1F0FA),
    onSurface = Color(0xFFF1F0FA),
    onSurfaceVariant = Color(0xFFB9B8CA),
    error = Color(0xFFFF777F)
)
private val LightScheme = lightColorScheme(
    primary = Color(0xFF5C4BD8),
    secondary = Color(0xFF087D69),
    background = Color(0xFFF6F5FB),
    surface = Color.White,
    surfaceVariant = Color(0xFFECEAF5),
    onPrimary = Color.White,
    onBackground = Color(0xFF181827),
    onSurface = Color(0xFF181827),
    onSurfaceVariant = Color(0xFF55546A)
)

@Composable
fun OpenGDSTheme(theme: String, content: @Composable () -> Unit) {
    val dark = when (theme) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }
    MaterialTheme(colorScheme = if (dark) DarkScheme else LightScheme, content = content)
}
