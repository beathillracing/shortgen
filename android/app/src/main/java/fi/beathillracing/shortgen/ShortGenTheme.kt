package fi.beathillracing.shortgen

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

enum class ThemeMode(val preferenceValue: String, val label: String) {
    System("system", "System default"),
    Light("light", "Light"),
    Dark("dark", "Dark");

    companion object {
        fun fromPreference(value: String?) =
            entries.firstOrNull { it.preferenceValue == value } ?: System
    }
}

private val LightColors = lightColorScheme(
    primary = Color(0xFF167A45),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFB7F3CB),
    onPrimaryContainer = Color(0xFF00210F),
    secondary = Color(0xFF476452),
    tertiary = Color(0xFF3B6470),
    background = Color(0xFFF7F9F7),
    surface = Color(0xFFF7F9F7),
    surfaceVariant = Color(0xFFE0E4E0),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF78D99A),
    onPrimary = Color(0xFF00391B),
    primaryContainer = Color(0xFF005228),
    onPrimaryContainer = Color(0xFF96F7B4),
    secondary = Color(0xFFADCDB7),
    tertiary = Color(0xFFA2CEDA),
    background = Color(0xFF111411),
    surface = Color(0xFF111411),
    surfaceVariant = Color(0xFF414942),
)

@Composable
fun ShortGenTheme(
    themeMode: ThemeMode,
    content: @Composable () -> Unit,
) {
    val systemDark = isSystemInDarkTheme()
    val darkTheme = when (themeMode) {
        ThemeMode.System -> systemDark
        ThemeMode.Light -> false
        ThemeMode.Dark -> true
    }
    val colors = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current

    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colors.background.toArgb()
            window.navigationBarColor = colors.background.toArgb()
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }

    MaterialTheme(
        colorScheme = colors,
        content = content,
    )
}
