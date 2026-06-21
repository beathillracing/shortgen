package fi.beathillracing.shortgen

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Environment
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.content.edit
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.TimeUnit

@Composable
fun UploadScreen(
    padding: PaddingValues,
    server: String,
    token: String,
    onOpenJob: (String) -> Unit,
    onOpenSettings: () -> Unit,
) {
    val context = LocalContext.current
    val workManager = remember { WorkManager.getInstance(context) }
    val workInfos by workManager
        .getWorkInfosForUniqueWorkFlow(WORK_NAME)
        .collectAsState(initial = emptyList())
    val currentWork = workInfos.firstOrNull()
    val account by produceState<AccountStatus?>(initialValue = null, server, token) {
        if (token.isBlank() || !server.startsWith("https://")) return@produceState
        value = runCatching {
            ShortGenApi(server.trimEnd('/'), token).getAccount()
        }.getOrNull()
    }
    val prefs = remember { context.getSharedPreferences(UploadWorker.PREFERENCES, Context.MODE_PRIVATE) }
    var contextText by remember { mutableStateOf("") }
    var selectedUris by remember { mutableStateOf<List<Uri>>(emptyList()) }
    var minimalCuts by remember { mutableStateOf(prefs.getBoolean("opt_minimal_cuts", false)) }
    var burnCaptions by remember { mutableStateOf(prefs.getBoolean("opt_burn_captions", true)) }
    var precaptioned by remember { mutableStateOf(prefs.getBoolean("opt_precaptioned", false)) }
    var highlightColor by remember {
        mutableStateOf(prefs.getString("opt_highlight_color", "#4CAF50") ?: "#4CAF50")
    }

    val picker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        selectedUris = uris
        uris.forEach {
            runCatching {
                context.contentResolver.takePersistableUriPermission(
                    it,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }
        }
    }
    val notificationPermission = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) {}

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (token.isBlank()) {
            Text("Set the mobile API token before uploading.")
            Button(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth()) {
                Text("Open settings")
            }
            return@Column
        }

        OutlinedButton(
            onClick = { picker.launch(arrayOf("video/*")) },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Outlined.VideoLibrary, contentDescription = null)
            Spacer(Modifier.size(8.dp))
            Text(if (selectedUris.isEmpty()) "Select videos" else "${selectedUris.size} video(s) selected")
        }

        OutlinedTextField(
            value = contextText,
            onValueChange = { contextText = it },
            label = { Text("Video context") },
            minLines = 2,
            modifier = Modifier.fillMaxWidth(),
        )

        ToggleRow("Karaoke captions", burnCaptions && !precaptioned) {
            burnCaptions = it
        }
        ToggleRow("Minimal cuts", minimalCuts && !precaptioned) {
            minimalCuts = it
        }
        ToggleRow("Already captioned", precaptioned) {
            precaptioned = it
            if (it) {
                burnCaptions = false
                minimalCuts = false
            }
        }

        if (burnCaptions && !precaptioned) {
            Text("Caption highlight color", style = MaterialTheme.typography.bodyMedium)
            ColorPalette(highlightColor) { highlightColor = it }
        }

        account?.let { acct ->
            acct.usage.limit?.let { limit ->
                Text(
                    "${acct.usage.remaining ?: 0} of $limit free jobs left this month",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Button(
            onClick = {
                if (
                    Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    ContextCompat.checkSelfPermission(
                        context,
                        Manifest.permission.POST_NOTIFICATIONS,
                    ) != PackageManager.PERMISSION_GRANTED
                ) {
                    notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
                prefs.edit {
                    putBoolean("opt_burn_captions", burnCaptions)
                    putBoolean("opt_minimal_cuts", minimalCuts)
                    putBoolean("opt_precaptioned", precaptioned)
                    putString("opt_highlight_color", highlightColor)
                }
                val tokenRef = "upload_token_${UUID.randomUUID()}"
                SecureStore.put(context, tokenRef, token)
                val request = OneTimeWorkRequestBuilder<UploadWorker>()
                    .addTag(JobMonitorWorker.WORK_TAG)
                    .setInputData(
                        Data.Builder()
                            .putString(UploadWorker.KEY_BASE_URL, server.trimEnd('/'))
                            .putString(UploadWorker.KEY_TOKEN_REF, tokenRef)
                            .putStringArray(
                                UploadWorker.KEY_URIS,
                                selectedUris.map(Uri::toString).toTypedArray(),
                            )
                            .putString(UploadWorker.KEY_CONTEXT, contextText)
                            .putBoolean(UploadWorker.KEY_MINIMAL_CUTS, minimalCuts)
                            .putBoolean(UploadWorker.KEY_BURN_CAPTIONS, burnCaptions)
                            .putBoolean(UploadWorker.KEY_PRECAPTIONED, precaptioned)
                            .putString(UploadWorker.KEY_REMOVE_OUTRO, "3")
                            .putString(UploadWorker.KEY_HIGHLIGHT_COLOR, highlightColor)
                            .build(),
                    )
                    .setConstraints(
                        Constraints.Builder()
                            .setRequiredNetworkType(NetworkType.CONNECTED)
                            .build(),
                    )
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                    .build()
                workManager.enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
            },
            enabled = selectedUris.isNotEmpty() &&
                currentWork?.state !in setOf(WorkInfo.State.RUNNING, WorkInfo.State.ENQUEUED),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Default.Upload, contentDescription = null)
            Spacer(Modifier.size(8.dp))
            Text("Upload and process")
        }

        WorkStatus(currentWork)
        if (currentWork?.state == WorkInfo.State.RUNNING ||
            currentWork?.state == WorkInfo.State.ENQUEUED
        ) {
            OutlinedButton(
                onClick = { workManager.cancelUniqueWork(WORK_NAME) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Cancel upload") }
        }
        val jobId = currentWork?.outputData?.getString(UploadWorker.KEY_JOB_ID)
        if (currentWork?.state == WorkInfo.State.SUCCEEDED && jobId != null) {
            Button(onClick = { onOpenJob(jobId) }, modifier = Modifier.fillMaxWidth()) {
                Text("Review job")
            }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun JobsScreen(
    padding: PaddingValues,
    api: ShortGenApi?,
    onOpenJob: (String) -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var jobs by remember { mutableStateOf<List<JobSummary>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshKey by remember { mutableStateOf(0) }
    var pendingDelete by remember { mutableStateOf<JobSummary?>(null) }
    var refreshing by remember { mutableStateOf(false) }

    LaunchedEffect(api, refreshKey) {
        if (api == null) return@LaunchedEffect
        while (true) {
            runCatching { api.listJobs() }
                .onSuccess {
                    jobs = it
                    error = null
                }
                .onFailure { error = it.message }
            refreshing = false
            delay(5000)
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(padding)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("Recent jobs", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            IconButton(onClick = { refreshKey += 1 }, enabled = api != null) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh")
            }
        }
        PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = {
                refreshing = true
                refreshKey += 1
            },
            modifier = Modifier.fillMaxSize(),
        ) {
        when {
            api == null -> {
                Button(
                    onClick = onOpenSettings,
                    modifier = Modifier.padding(16.dp).fillMaxWidth(),
                ) { Text("Configure connection") }
            }
            error != null && jobs.isEmpty() -> {
                Text(error.orEmpty(), color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
            }
            jobs.isEmpty() -> {
                Text(
                    "No videos yet. Upload one to get started.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp),
                )
            }
            else -> LazyColumn(
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(jobs, key = { it.id }) { job ->
                    JobRow(
                        job = job,
                        onClick = { onOpenJob(job.id) },
                        onDelete = { pendingDelete = job },
                    )
                }
            }
        }
        }
    }

    pendingDelete?.let { target ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete job?") },
            text = { Text("This permanently deletes ${target.filename} and its files.") },
            confirmButton = {
                Button(onClick = {
                    pendingDelete = null
                    scope.launch {
                        runCatching { api?.deleteJob(target.id) }
                            .onSuccess { refreshKey += 1 }
                            .onFailure { error = it.message }
                    }
                }) { Text("Delete") }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingDelete = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun JobRow(job: JobSummary, onClick: () -> Unit, onDelete: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
            .clickable(onClick = onClick)
            .padding(start = 14.dp, top = 14.dp, bottom = 14.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(job.filename, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(job.status.replace("_", " "), color = statusColor(job.status))
                Text(formatDate(job.createdAt), style = MaterialTheme.typography.bodySmall)
            }
            if (job.status !in setOf("review", "completed", "failed")) {
                LinearProgressIndicator(
                    progress = { job.progress / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    "${job.currentStep.orEmpty().ifBlank { "Processing" }}  ${job.progress}%",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            job.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
        IconButton(onClick = onDelete) {
            Icon(
                Icons.Outlined.Delete,
                contentDescription = "Delete job",
                tint = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
fun JobDetailScreen(
    padding: PaddingValues,
    api: ShortGenApi,
    jobId: String,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var job by remember { mutableStateOf<JobDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshKey by remember { mutableStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var connections by remember { mutableStateOf<Map<String, PlatformConnection>>(emptyMap()) }

    LaunchedEffect(jobId, refreshKey) {
        while (true) {
            val current = runCatching { api.getJob(jobId) }
                .onSuccess {
                    job = it
                    error = null
                }
                .onFailure { error = it.message }
                .getOrNull()
            if (current?.publishingEnabled == true && connections.isEmpty()) {
                runCatching { api.getConnections() }
                    .onSuccess { connections = it }
                    .onFailure { error = it.message }
            }
            val status = current?.summary?.status
            val publishState = current?.publishStatus?.optString("status", "idle") ?: "idle"
            val publishing = publishState == "queued" || publishState == "running"
            // Stop the 3s poll once the job is settled; user actions bump refreshKey
            // to restart it, and active publishing keeps it alive.
            val settled = status == "failed" ||
                ((status == "review" || status == "completed") && !publishing)
            if (settled) break
            delay(3000)
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(padding)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text(
                job?.summary?.filename ?: "Loading",
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                fontWeight = FontWeight.SemiBold,
            )
        }
        when {
            error != null && job == null -> Text(
                error.orEmpty(),
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(16.dp),
            )
            job == null -> LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            else -> {
                error?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
                JobContent(
                    job = job!!,
                    api = api,
                    busy = busy,
                    connections = connections,
                    onOpenSettings = onOpenSettings,
                    onAction = { action ->
                        busy = true
                        scope.launch {
                            runCatching { action() }
                                .onFailure { error = it.message }
                            busy = false
                            refreshKey += 1
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun JobContent(
    job: JobDetail,
    api: ShortGenApi,
    busy: Boolean,
    connections: Map<String, PlatformConnection>,
    onOpenSettings: () -> Unit,
    onAction: (suspend () -> Unit) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(
            job.summary.status.replace("_", " "),
            color = statusColor(job.summary.status),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )

        when (job.summary.status) {
            "thumbnail_selection" -> ThumbnailSelection(
                job = job,
                api = api,
                busy = busy,
                continueProcessing = { index, fi, en, color ->
                    onAction { api.continueJob(job.summary.id, index, fi, en, color) }
                },
            )
            "review", "completed" -> ReviewAndPublish(
                job = job,
                api = api,
                busy = busy,
                connections = connections,
                onOpenSettings = onOpenSettings,
                onAction = onAction,
            )
            "failed" -> Text(
                job.summary.error ?: "Processing failed",
                color = MaterialTheme.colorScheme.error,
            )
            else -> {
                LinearProgressIndicator(
                    progress = { job.summary.progress / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    "${job.summary.currentStep?.takeIf { it.isNotBlank() } ?: "Processing"}  ${job.summary.progress}%",
                )
            }
        }
    }
}

@Composable
private fun ThumbnailSelection(
    job: JobDetail,
    api: ShortGenApi,
    busy: Boolean,
    continueProcessing: (Int, String, String, String) -> Unit,
) {
    var selected by remember(job.summary.id) { mutableStateOf(job.selectedThumbnailIndex) }
    var textFi by remember(job.summary.id) { mutableStateOf(job.thumbnailTextFi) }
    var textEn by remember(job.summary.id) { mutableStateOf(job.thumbnailTextEn) }
    var textColor by remember(job.summary.id) { mutableStateOf("#4CAF50") }
    Text("Choose thumbnail", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    CandidateStrip(job.candidates, selected, api) { selected = it }
    OutlinedTextField(
        value = textFi,
        onValueChange = { textFi = it },
        label = { Text("Finnish thumbnail text") },
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedTextField(
        value = textEn,
        onValueChange = { textEn = it },
        label = { Text("English thumbnail text") },
        modifier = Modifier.fillMaxWidth(),
    )
    Text("Thumbnail text color", style = MaterialTheme.typography.bodyMedium)
    ColorPalette(textColor) { textColor = it }
    Button(
        onClick = { continueProcessing(selected, textFi, textEn, textColor) },
        enabled = !busy,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(if (busy) "Starting..." else "Continue processing") }
}

@Composable
private fun ReviewAndPublish(
    job: JobDetail,
    api: ShortGenApi,
    busy: Boolean,
    connections: Map<String, PlatformConnection>,
    onOpenSettings: () -> Unit,
    onAction: (suspend () -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val pubPrefs = LocalContext.current.getSharedPreferences(UploadWorker.PREFERENCES, Context.MODE_PRIVATE)
    var language by remember { mutableStateOf(pubPrefs.getString("pub_language", "fi") ?: "fi") }
    var titleFi by remember(job.summary.id) { mutableStateOf(job.titleFi) }
    var titleEn by remember(job.summary.id) { mutableStateOf(job.titleEn) }
    var descriptionFi by remember(job.summary.id) { mutableStateOf(job.descriptionFi) }
    var descriptionEn by remember(job.summary.id) { mutableStateOf(job.descriptionEn) }
    val title = if (language == "fi") titleFi else titleEn
    val description = if (language == "fi") descriptionFi else descriptionEn
    var thumbnail by remember { mutableStateOf(pubPrefs.getString("pub_thumbnail", "fi") ?: "fi") }
    var contentType by remember { mutableStateOf(pubPrefs.getString("pub_content_type", "short") ?: "short") }
    var youtube by remember(job.posted.youtube) { mutableStateOf(false) }
    var instagram by remember(job.posted.instagram) { mutableStateOf(false) }
    var facebook by remember(job.posted.facebook) { mutableStateOf(false) }
    var tiktok by remember(job.posted.tiktok) { mutableStateOf(false) }
    var selectedCandidate by remember(job.summary.id) { mutableStateOf(job.selectedThumbnailIndex) }
    var thumbnailTextFi by remember(job.summary.id) { mutableStateOf(job.thumbnailTextFi) }
    var thumbnailTextEn by remember(job.summary.id) { mutableStateOf(job.thumbnailTextEn) }
    var thumbnailTextColor by remember(job.summary.id) { mutableStateOf("#4CAF50") }

    if (job.hasVideo) {
        AuthVideo(api, job.media.getValue("video"))
    }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(
            selected = language == "fi",
            onClick = { language = "fi" },
            label = { Text("Finnish") },
        )
        FilterChip(
            selected = language == "en",
            onClick = { language = "en" },
            label = { Text("English") },
        )
    }
    OutlinedTextField(
        value = title,
        onValueChange = { if (language == "fi") titleFi = it else titleEn = it },
        label = { Text("Title") },
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedTextField(
        value = description,
        onValueChange = { if (language == "fi") descriptionFi = it else descriptionEn = it },
        label = { Text("Description") },
        minLines = 4,
        modifier = Modifier.fillMaxWidth(),
    )
    OutlinedButton(
        onClick = { onAction { api.updateMetadata(job.summary.id, title, description) } },
        enabled = !busy,
        modifier = Modifier.fillMaxWidth(),
    ) { Text("Save metadata") }

    ExportSection(
        job = job,
        api = api,
        language = language,
        title = title,
        description = description,
    )

    HorizontalDivider()
    Text("Thumbnail", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    if (job.candidates.isNotEmpty()) {
        CandidateStrip(job.candidates, selectedCandidate, api) { selectedCandidate = it }
        OutlinedTextField(
            value = thumbnailTextFi,
            onValueChange = { thumbnailTextFi = it },
            label = { Text("Finnish thumbnail text") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = thumbnailTextEn,
            onValueChange = { thumbnailTextEn = it },
            label = { Text("English thumbnail text") },
            modifier = Modifier.fillMaxWidth(),
        )
        Text("Thumbnail text color", style = MaterialTheme.typography.bodyMedium)
        ColorPalette(thumbnailTextColor) { thumbnailTextColor = it }
        OutlinedButton(
            onClick = {
                onAction {
                    api.applyThumbnail(
                        job.summary.id,
                        selectedCandidate,
                        thumbnailTextFi,
                        thumbnailTextEn,
                        thumbnailTextColor,
                    )
                }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Apply thumbnail") }
    }

    if (!job.publishingEnabled) {
        HorizontalDivider()
        Text("Beathill Studio Free", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("Video creation and downloads are enabled. Direct publishing requires Pro access.")
        return
    }

    HorizontalDivider()
    Text("Publish", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    val youtubeConnection = connections["youtube"]
    val facebookConnection = connections["facebook"]
    val instagramConnection = connections["instagram"]
    val tiktokConnection = connections["tiktok"]
    PlatformRow(
        label = "YouTube",
        selected = youtube,
        posted = job.posted.youtube,
        connection = youtubeConnection,
    ) { youtube = it }
    PlatformRow(
        label = "Instagram",
        selected = instagram,
        posted = job.posted.instagram,
        connection = instagramConnection,
    ) { instagram = it }
    PlatformRow(
        label = "Facebook",
        selected = facebook,
        posted = job.posted.facebook,
        connection = facebookConnection,
    ) { facebook = it }
    PlatformRow(
        label = "TikTok draft",
        selected = tiktok,
        posted = job.posted.tiktok,
        connection = tiktokConnection,
    ) { tiktok = it }
    if (connections.isEmpty() || connections.values.any { !it.connected }) {
        OutlinedButton(
            onClick = onOpenSettings,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Manage publishing accounts") }
    }

    Text("Thumbnail / cover", fontWeight = FontWeight.SemiBold)
    ChoiceRow(
        choices = listOf("fi" to "Finnish", "en" to "English", "clean" to "Clean"),
        selected = thumbnail,
        onSelected = { thumbnail = it },
    )
    if (youtube) {
        Text("YouTube type", fontWeight = FontWeight.SemiBold)
        ChoiceRow(
            choices = listOf("short" to "Short", "video" to "Video"),
            selected = contentType,
            onSelected = { contentType = it },
        )
        if (contentType == "short") {
            Text(
                "YouTube can't set a Shorts thumbnail via API - set it in YouTube Studio after upload.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    val selectedPlatforms = buildList {
        if (youtube) add("youtube")
        if (instagram) add("instagram")
        if (facebook) add("facebook")
        if (tiktok) add("tiktok")
    }
    Button(
        onClick = {
            pubPrefs.edit {
                putString("pub_language", language)
                putString("pub_thumbnail", thumbnail)
                putString("pub_content_type", contentType)
            }
            onAction {
                api.updateMetadata(job.summary.id, title, description)
                api.publish(job.summary.id, selectedPlatforms, language, thumbnail, contentType)
            }
        },
        enabled = !busy && selectedPlatforms.isNotEmpty(),
        modifier = Modifier.fillMaxWidth(),
    ) { Text(if (busy) "Working..." else "Publish selected") }

    val publishState = job.publishStatus.optString("status", "idle")
    if (publishState != "idle") {
        val completed = job.publishStatus.optInt("completed", 0)
        val total = job.publishStatus.optInt("total", 0)
        val currentPlatform = job.publishStatus.optString("current_platform")
        Text(
            when {
                publishState == "running" && currentPlatform.isNotBlank() ->
                    "Publishing to ${platformLabel(currentPlatform)}"
                else -> "Publishing: ${publishState.replace("_", " ")}"
            },
            fontWeight = FontWeight.SemiBold,
        )
        if (publishState in setOf("queued", "running")) {
            if (total > 0) {
                LinearProgressIndicator(
                    progress = { completed.toFloat() / total.toFloat() },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    "$completed of $total platforms completed",
                    style = MaterialTheme.typography.bodySmall,
                )
            } else {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
        }
        val results = job.publishStatus.optJSONObject("results")
        results?.keys()?.forEach { platform ->
            val result = results.optJSONObject(platform) ?: return@forEach
            val url = result.optString("url").takeIf { it.startsWith("http") }
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    "${platformLabel(platform)}: ${result.optString("status", "completed").replace("_", " ")}",
                    color = MaterialTheme.colorScheme.primary,
                )
                if (url != null) {
                    OutlinedButton(
                        onClick = {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        },
                    ) { Text("Open") }
                }
            }
        }
        val errors = job.publishStatus.optJSONObject("errors")
        errors?.keys()?.forEach { platform ->
            Text(
                "${platformLabel(platform)}: ${errors.optString(platform, "Publishing failed")}",
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

private fun platformLabel(platform: String): String = when (platform) {
    "youtube" -> "YouTube"
    "instagram" -> "Instagram"
    "facebook" -> "Facebook"
    "tiktok" -> "TikTok"
    else -> platform.replaceFirstChar { it.uppercase() }
}

@Composable
private fun ExportSection(
    job: JobDetail,
    api: ShortGenApi,
    language: String,
    title: String,
    description: String,
) {
    val context = LocalContext.current
    val hashtags = job.hashtags.joinToString(" ") { "#${it.removePrefix("#")}" }
    val allText = listOf(title, description, hashtags).filter { it.isNotBlank() }.joinToString("\n\n")

    HorizontalDivider()
    Text("Export", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
    if (job.hasVideo) {
        Button(
            onClick = {
                enqueueDownload(
                    context,
                    api,
                    job.media.getValue("video"),
                    "shortgen-${job.summary.id.take(8)}.mp4",
                    "video/mp4",
                )
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Download video") }
    }
    if (job.hasThumbnail) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = {
                    enqueueDownload(
                        context,
                        api,
                        job.media.getValue("thumbnail_${language}"),
                        "shortgen-${job.summary.id.take(8)}-$language.jpg",
                        "image/jpeg",
                    )
                },
                modifier = Modifier.weight(1f),
            ) { Text("Download thumbnail") }
            OutlinedButton(
                onClick = {
                    enqueueDownload(
                        context,
                        api,
                        job.media.getValue("thumbnail_clean"),
                        "shortgen-${job.summary.id.take(8)}-clean.jpg",
                        "image/jpeg",
                    )
                },
                modifier = Modifier.weight(1f),
            ) { Text("Clean thumbnail") }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(
            onClick = { copyText(context, "ShortGen title", title) },
            enabled = title.isNotBlank(),
            modifier = Modifier.weight(1f),
        ) { Text("Copy title") }
        OutlinedButton(
            onClick = { copyText(context, "ShortGen description", description) },
            enabled = description.isNotBlank(),
            modifier = Modifier.weight(1f),
        ) { Text("Copy description") }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(
            onClick = { copyText(context, "ShortGen hashtags", hashtags) },
            enabled = hashtags.isNotBlank(),
            modifier = Modifier.weight(1f),
        ) { Text("Copy hashtags") }
        Button(
            onClick = { copyText(context, "ShortGen metadata", allText) },
            enabled = allText.isNotBlank(),
            modifier = Modifier.weight(1f),
        ) { Text("Copy all text") }
    }
}

@Composable
private fun ColorPalette(selected: String, onSelected: (String) -> Unit) {
    val colors = listOf(
        "#4CAF50", "#FFEB3B", "#FF5252", "#FFFFFF",
        "#2196F3", "#FF4081", "#FF9800", "#00E5FF",
    )
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        colors.forEach { hex ->
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .background(Color(android.graphics.Color.parseColor(hex)), CircleShape)
                    .border(
                        width = if (hex == selected) 3.dp else 1.dp,
                        color = if (hex == selected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outline,
                        shape = CircleShape,
                    )
                    .clickable { onSelected(hex) },
            )
        }
    }
}

@Composable
private fun CandidateStrip(
    candidates: List<ThumbnailCandidate>,
    selected: Int,
    api: ShortGenApi,
    onSelected: (Int) -> Unit,
) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(candidates, key = { it.index }) { candidate ->
            Column(
                modifier = Modifier
                    .size(width = 130.dp, height = 230.dp)
                    .background(
                        if (candidate.index == selected) MaterialTheme.colorScheme.primaryContainer
                        else MaterialTheme.colorScheme.surfaceVariant,
                        RoundedCornerShape(6.dp),
                    )
                    .clickable { onSelected(candidate.index) }
                    .padding(4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                AuthImage(
                    api = api,
                    path = candidate.path,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                )
                Text("#${candidate.index}", modifier = Modifier.padding(4.dp))
            }
        }
    }
}

@Composable
private fun AuthImage(api: ShortGenApi, path: String, modifier: Modifier = Modifier) {
    val bitmap by produceState<android.graphics.Bitmap?>(initialValue = null, api, path) {
        value = runCatching {
            val bytes = api.loadBytes(path)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }.getOrNull()
    }
    Box(modifier = modifier.background(MaterialTheme.colorScheme.surface)) {
        bitmap?.let {
            Image(
                bitmap = it.asImageBitmap(),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
@SuppressLint("UnsafeOptInUsageError")
private fun AuthVideo(api: ShortGenApi, path: String) {
    val context = LocalContext.current
    val player = remember(api, path) {
        val dataSource = DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(api.authHeaders())
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(ProgressiveMediaSource.Factory(dataSource))
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(api.absoluteUrl(path)))
                prepare()
            }
    }
    DisposableEffect(player) {
        onDispose { player.release() }
    }
    AndroidView(
        factory = { PlayerView(it).apply { this.player = player } },
        modifier = Modifier.fillMaxWidth().aspectRatio(9f / 16f),
    )
}

@Composable
private fun PlatformRow(
    label: String,
    selected: Boolean,
    posted: Boolean,
    connection: PlatformConnection?,
    available: Boolean = connection?.connected == true,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = selected,
            onCheckedChange = onChange,
            enabled = !posted && available,
        )
        val suffix = when {
            posted -> "posted"
            available -> connection?.label ?: "connected"
            else -> "not connected"
        }
        Text("$label ($suffix)")
    }
}

@Composable
private fun ChoiceRow(
    choices: List<Pair<String, String>>,
    selected: String,
    onSelected: (String) -> Unit,
) {
    Column {
        choices.forEach { (value, label) ->
            Row(
                modifier = Modifier.fillMaxWidth().clickable { onSelected(value) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(selected = selected == value, onClick = { onSelected(value) })
                Text(label)
            }
        }
    }
}

@Composable
fun SettingsScreen(
    padding: PaddingValues,
    initialServer: String,
    initialToken: String,
    initialThemeMode: ThemeMode,
    onThemeChanged: (ThemeMode) -> Unit,
    onSaved: () -> Unit,
    onConfigChanged: () -> Unit,
) {
    val context = LocalContext.current
    val preferences = remember {
        context.getSharedPreferences(UploadWorker.PREFERENCES, android.content.Context.MODE_PRIVATE)
    }
    var server by remember(initialServer) { mutableStateOf(initialServer) }
    var token by remember(initialToken) { mutableStateOf(initialToken) }
    var themeMode by remember(initialThemeMode) { mutableStateOf(initialThemeMode) }
    DisposableEffect(Unit) {
        onDispose { onConfigChanged() }
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Connection", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(
            if (token.isBlank()) "Setting up your private account..." else "Connected",
            color = if (token.isBlank()) {
                MaterialTheme.colorScheme.onSurfaceVariant
            } else {
                MaterialTheme.colorScheme.primary
            },
        )
        OutlinedTextField(
            value = token,
            onValueChange = {
                token = it
                if (it.isNotBlank()) SecureStore.put(context, UploadWorker.KEY_TOKEN, it.trim())
            },
            label = { Text("Access code") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "Normally configured automatically. Enter a support or administrator code here only when needed.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = server,
            onValueChange = {
                server = it
                if (it.startsWith("https://")) {
                    preferences.edit { putString(UploadWorker.KEY_BASE_URL, it.trimEnd('/')) }
                }
            },
            label = { Text("Server") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        DistributionAccountSection(
            server = server.trimEnd('/'),
            token = token,
            preferences = preferences,
            onAccountChanged = onSaved,
        )
        HorizontalDivider()
        Text("Appearance", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        ThemeMode.entries.forEach { mode ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable {
                        themeMode = mode
                        preferences.edit { putString(KEY_THEME_MODE, mode.preferenceValue) }
                        onThemeChanged(mode)
                    },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RadioButton(
                    selected = themeMode == mode,
                    onClick = {
                        themeMode = mode
                        preferences.edit { putString(KEY_THEME_MODE, mode.preferenceValue) }
                        onThemeChanged(mode)
                    },
                )
                Text(mode.label)
            }
        }
        Text(
            "Text size follows the Android display and font-size settings.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        HorizontalDivider()
        Text("About", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text("Beathill Studio ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
        HorizontalDivider()
        Text(
            "Settings are saved automatically.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label)
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun WorkStatus(workInfo: WorkInfo?) {
    if (workInfo == null) return
    val progress = workInfo.progress.getInt(UploadWorker.KEY_PROGRESS, 0)
    val label = when (workInfo.state) {
        WorkInfo.State.ENQUEUED -> "Waiting for network"
        WorkInfo.State.RUNNING -> "Uploading $progress%"
        WorkInfo.State.SUCCEEDED -> "Upload complete. Processing started."
        WorkInfo.State.FAILED -> workInfo.outputData.getString(UploadWorker.KEY_ERROR) ?: "Upload failed"
        WorkInfo.State.BLOCKED -> "Upload blocked"
        WorkInfo.State.CANCELLED -> "Upload cancelled"
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label)
        if (workInfo.state == WorkInfo.State.RUNNING || workInfo.state == WorkInfo.State.ENQUEUED) {
            LinearProgressIndicator(
                progress = { progress / 100f },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun statusColor(status: String) = when (status) {
    "review", "completed" -> MaterialTheme.colorScheme.primary
    "failed" -> MaterialTheme.colorScheme.error
    "thumbnail_selection" -> MaterialTheme.colorScheme.tertiary
    else -> MaterialTheme.colorScheme.secondary
}

private fun formatDate(value: String?): String {
    if (value.isNullOrBlank()) return ""
    return runCatching {
        OffsetDateTime.parse(value).format(DateTimeFormatter.ofPattern("dd.MM HH:mm"))
    }.getOrDefault(value.take(16).replace("T", " "))
}

private fun enqueueDownload(
    context: Context,
    api: ShortGenApi,
    path: String,
    filename: String,
    mimeType: String,
) {
    val request = DownloadManager.Request(Uri.parse(api.absoluteUrl(path)))
        .setMimeType(mimeType)
        .setTitle(filename)
        .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
        .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
    api.authHeaders().forEach(request::addRequestHeader)
    context.getSystemService(DownloadManager::class.java).enqueue(request)
}

private fun copyText(context: Context, label: String, text: String) {
    context.getSystemService(ClipboardManager::class.java)
        .setPrimaryClip(ClipData.newPlainText(label, text))
}
