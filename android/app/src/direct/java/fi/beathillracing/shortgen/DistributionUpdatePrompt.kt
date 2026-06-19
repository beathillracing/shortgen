package fi.beathillracing.shortgen

import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.io.File

@Composable
fun DistributionUpdatePrompt(server: String, token: String, configured: Boolean) {
    val context = LocalContext.current
    var availableUpdate by remember { mutableStateOf<AppUpdate?>(null) }
    var downloadedUpdate by remember { mutableStateOf<File?>(null) }
    var updateDownloading by remember { mutableStateOf(false) }
    var updateProgress by remember { mutableStateOf(0) }
    var updateError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val unknownSourcesLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        val apk = downloadedUpdate
        if (
            apk != null &&
            (Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
                context.packageManager.canRequestPackageInstalls())
        ) {
            context.startActivity(UpdateInstaller.installIntent(context, apk))
            downloadedUpdate = null
        } else if (apk != null) {
            updateError = "Allow ShortGen to install apps, then press Download update again."
        }
    }

    fun openInstaller(apk: File) {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !context.packageManager.canRequestPackageInstalls()
        ) {
            downloadedUpdate = apk
            unknownSourcesLauncher.launch(UpdateInstaller.unknownSourcesIntent(context))
        } else {
            context.startActivity(UpdateInstaller.installIntent(context, apk))
        }
    }

    LaunchedEffect(server, token, configured) {
        if (configured) {
            availableUpdate = runCatching {
                ShortGenApi(server.trimEnd('/'), token).getAppUpdate(BuildConfig.VERSION_CODE)
            }.getOrNull()?.takeIf { it.versionCode > BuildConfig.VERSION_CODE }
        }
    }

    availableUpdate?.let { update ->
        AlertDialog(
            onDismissRequest = { availableUpdate = null },
            title = { Text("ShortGen update available") },
            text = {
                val notes = update.missedReleases.joinToString("\n\n") {
                    "${it.versionName}\n${it.notes}"
                }
                Column {
                    Text(
                        "Version ${update.versionName}\n\n$notes\n\n" +
                            "ShortGen will download and verify the update. Android will ask you to confirm installation.",
                    )
                    if (updateDownloading) {
                        Spacer(Modifier.height(12.dp))
                        LinearProgressIndicator(progress = { updateProgress / 100f })
                    }
                    updateError?.let {
                        Spacer(Modifier.height(12.dp))
                        Text(it, color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        updateDownloading = true
                        updateProgress = 0
                        updateError = null
                        scope.launch {
                            runCatching {
                                UpdateInstaller.download(context, update) {
                                    updateProgress = it
                                }
                            }.onSuccess { apk ->
                                updateDownloading = false
                                openInstaller(apk)
                            }.onFailure {
                                updateDownloading = false
                                updateError = it.message ?: "Update failed"
                            }
                        }
                    },
                    enabled = !updateDownloading,
                ) {
                    Text(if (updateDownloading) "Downloading..." else "Download update")
                }
            },
            dismissButton = {
                Button(
                    onClick = { availableUpdate = null },
                    enabled = !updateDownloading,
                ) {
                    Text("Later")
                }
            },
        )
    }
}
