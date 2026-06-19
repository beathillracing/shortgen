package fi.beathillracing.shortgen

import android.content.SharedPreferences
import androidx.compose.runtime.Composable

@Composable
fun DistributionAccountSection(
    server: String,
    token: String,
    preferences: SharedPreferences,
    onAccountChanged: () -> Unit,
) = Unit
