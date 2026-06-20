package fi.beathillracing.shortgen

import android.app.Activity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.InstallStateUpdatedListener
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.InstallStatus
import com.google.android.play.core.install.model.UpdateAvailability

// Play In-App Updates: checks whether a newer version is live on the user's
// Play track and offers a flexible update (background download, then restart to
// install). No-op when the app was not installed from Play.
@Composable
fun DistributionUpdatePrompt(server: String, token: String, configured: Boolean) {
    val context = LocalContext.current
    val activity = context as? Activity ?: return
    val manager = remember { AppUpdateManagerFactory.create(context) }
    var downloaded by remember { mutableStateOf(false) }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { /* user accepted or dismissed; a flexible download continues in background */ }

    DisposableEffect(manager) {
        val listener = InstallStateUpdatedListener { state ->
            if (state.installStatus() == InstallStatus.DOWNLOADED) {
                downloaded = true
            }
        }
        manager.registerListener(listener)
        onDispose { manager.unregisterListener(listener) }
    }

    LaunchedEffect(Unit) {
        manager.appUpdateInfo.addOnSuccessListener { info ->
            when {
                info.installStatus() == InstallStatus.DOWNLOADED -> downloaded = true
                info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE &&
                    info.isUpdateTypeAllowed(AppUpdateType.FLEXIBLE) -> {
                    runCatching {
                        manager.startUpdateFlowForResult(
                            info,
                            launcher,
                            AppUpdateOptions.newBuilder(AppUpdateType.FLEXIBLE).build(),
                        )
                    }
                }
            }
        }
    }

    if (downloaded) {
        AlertDialog(
            onDismissRequest = { downloaded = false },
            title = { Text("Update ready") },
            text = { Text("A new version of Beathill Studio has been downloaded. Restart to install it?") },
            confirmButton = {
                Button(onClick = { manager.completeUpdate() }) { Text("Restart") }
            },
            dismissButton = {
                OutlinedButton(onClick = { downloaded = false }) { Text("Later") }
            },
        )
    }
}
