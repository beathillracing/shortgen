package fi.beathillracing.shortgen

import android.content.SharedPreferences
import androidx.compose.runtime.Composable

@Composable
fun DistributionAccountProvisioning(
    server: String,
    token: String,
    preferences: SharedPreferences,
    onProvisioned: () -> Unit,
) = Unit
