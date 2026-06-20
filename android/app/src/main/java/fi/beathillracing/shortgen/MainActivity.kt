package fi.beathillracing.shortgen

import android.os.Bundle
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val preferences = getSharedPreferences(
                UploadWorker.PREFERENCES,
                Context.MODE_PRIVATE,
            )
            var themeMode by remember {
                mutableStateOf(
                    ThemeMode.fromPreference(
                        preferences.getString(KEY_THEME_MODE, null),
                    ),
                )
            }
            ShortGenTheme(themeMode) {
                ShortGenApp(
                    themeMode = themeMode,
                    onThemeChanged = { themeMode = it },
                )
            }
        }
    }
}

private enum class AppTab(val label: String) {
    Upload("Upload"),
    Jobs("Jobs"),
    Settings("Settings"),
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun ShortGenApp(
    themeMode: ThemeMode,
    onThemeChanged: (ThemeMode) -> Unit,
) {
    val context = LocalContext.current
    val preferences = remember {
        context.getSharedPreferences(UploadWorker.PREFERENCES, Context.MODE_PRIVATE)
    }
    var tab by remember { mutableStateOf(AppTab.Upload) }
    var selectedJobId by remember { mutableStateOf<String?>(null) }
    var configVersion by remember { mutableStateOf(0) }
    val server = remember(configVersion) {
        preferences.getString(UploadWorker.KEY_BASE_URL, DEFAULT_SERVER) ?: DEFAULT_SERVER
    }
    val token = remember(configVersion) {
        preferences.getString(UploadWorker.KEY_TOKEN, "").orEmpty()
    }
    val configured = server.startsWith("https://") && token.isNotBlank()
    DistributionAccountProvisioning(
        server = server,
        token = token,
        preferences = preferences,
        onProvisioned = { configVersion += 1 },
    )
    DistributionUpdatePrompt(server, token, configured)

    BackHandler(enabled = selectedJobId != null) {
        selectedJobId = null
        tab = AppTab.Jobs
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        when {
                            selectedJobId != null -> "Job"
                            else -> tab.label
                        },
                    )
                },
            )
        },
        bottomBar = {
            if (selectedJobId == null) {
                NavigationBar {
                    NavigationBarItem(
                        selected = tab == AppTab.Upload,
                        onClick = { tab = AppTab.Upload },
                        icon = { Icon(Icons.Default.Upload, contentDescription = null) },
                        label = { Text("Upload") },
                    )
                    NavigationBarItem(
                        selected = tab == AppTab.Jobs,
                        onClick = { tab = AppTab.Jobs },
                        icon = { Icon(Icons.AutoMirrored.Filled.List, contentDescription = null) },
                        label = { Text("Jobs") },
                    )
                    NavigationBarItem(
                        selected = tab == AppTab.Settings,
                        onClick = { tab = AppTab.Settings },
                        icon = { Icon(Icons.Default.Settings, contentDescription = null) },
                        label = { Text("Settings") },
                    )
                }
            }
        },
    ) { padding ->
        when {
            selectedJobId != null && configured -> JobDetailScreen(
                padding = padding,
                api = remember(server, token) { ShortGenApi(server.trimEnd('/'), token) },
                jobId = selectedJobId!!,
                onBack = {
                    selectedJobId = null
                    tab = AppTab.Jobs
                },
                onOpenSettings = {
                    selectedJobId = null
                    tab = AppTab.Settings
                },
            )

            tab == AppTab.Upload -> UploadScreen(
                padding = padding,
                server = server,
                token = token,
                onOpenJob = { selectedJobId = it },
                onOpenSettings = { tab = AppTab.Settings },
            )

            tab == AppTab.Jobs -> JobsScreen(
                padding = padding,
                api = if (configured) {
                    remember(server, token) { ShortGenApi(server.trimEnd('/'), token) }
                } else {
                    null
                },
                onOpenJob = { selectedJobId = it },
                onOpenSettings = { tab = AppTab.Settings },
            )

            else -> SettingsScreen(
                padding = padding,
                initialServer = server,
                initialToken = token,
                initialThemeMode = themeMode,
                onThemeChanged = onThemeChanged,
                onSaved = {
                    configVersion += 1
                    tab = AppTab.Upload
                },
            )
        }
    }
}

const val DEFAULT_SERVER = "https://shortgen.beathillracing.fi"
const val WORK_NAME = "shortgen-video-upload"
const val KEY_THEME_MODE = "theme_mode"
