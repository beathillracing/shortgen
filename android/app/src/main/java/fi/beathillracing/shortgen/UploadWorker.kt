package fi.beathillracing.shortgen

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.core.app.NotificationCompat
import androidx.core.content.edit
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ForegroundInfo
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(5, TimeUnit.MINUTES)
        .build()

    private val preferences = appContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val baseUrl = inputData.getString(KEY_BASE_URL)?.trimEnd('/')
        val tokenRef = inputData.getString(KEY_TOKEN_REF)
        val token = tokenRef?.let { SecureStore.get(applicationContext, it) }
            ?: inputData.getString(KEY_TOKEN)
        val uriStrings = inputData.getStringArray(KEY_URIS)?.toList().orEmpty()
        if (baseUrl.isNullOrBlank() || token.isNullOrBlank() || uriStrings.isEmpty()) {
            return@withContext Result.failure(errorData("Missing server, token, or video"))
        }

        setForeground(createForegroundInfo(0, "Preparing upload"))

        try {
            val uris = uriStrings.map(Uri::parse)
            val files = uris.map(::queryFile)
            val sessionKey = "session_$id"
            var uploadId = preferences.getString(sessionKey, null)
            var chunkSize = DEFAULT_CHUNK_SIZE

            if (uploadId == null) {
                val session = createSession(baseUrl, token, files)
                uploadId = session.getString("upload_id")
                chunkSize = session.optInt("chunk_size", DEFAULT_CHUNK_SIZE)
                preferences.edit { putString(sessionKey, uploadId) }
            }

            val remote = getJson(baseUrl, token, "/api/mobile/uploads/$uploadId")
            val remoteFiles = remote.getJSONArray("files")
            val totalBytes = files.sumOf { it.size }

            files.forEachIndexed { index, file ->
                var offset = remoteFiles.getJSONObject(index).getLong("uploaded")
                while (offset < file.size) {
                    if (isStopped) throw IOException("Upload cancelled")
                    val length = minOf(chunkSize.toLong(), file.size - offset).toInt()
                    val bytes = readChunk(file.uri, offset, length)
                    putChunk(baseUrl, token, uploadId, index, offset, bytes)
                    offset += bytes.size

                    val completedBefore = files.take(index).sumOf { it.size }
                    val uploaded = completedBefore + offset
                    val percent = ((uploaded * 100L) / totalBytes).toInt().coerceIn(0, 100)
                    setProgress(Data.Builder().putInt(KEY_PROGRESS, percent).build())
                    setForeground(createForegroundInfo(percent, "Uploading ${file.name}"))
                }
            }

            val completed = postJson(
                baseUrl,
                token,
                "/api/mobile/uploads/$uploadId/complete",
                JSONObject(),
            )
            preferences.edit { remove(sessionKey) }
            val jobId = completed.getString("job_id")
            val monitorTokenRef = tokenRef ?: "job_token_${UUID.randomUUID()}".also {
                SecureStore.put(applicationContext, it, token)
            }
            enqueueJobMonitor(baseUrl, monitorTokenRef, jobId)
            Result.success(
                Data.Builder()
                    .putString(KEY_JOB_ID, jobId)
                    .putString(KEY_JOB_URL, "$baseUrl/job/$jobId")
                    .build(),
            )
        } catch (terminal: TerminalUploadException) {
            tokenRef?.let { SecureStore.remove(applicationContext, it) }
            Result.failure(errorData(terminal.message ?: "Upload failed"))
        } catch (error: Exception) {
            if (runAttemptCount < MAX_RETRIES) {
                Result.retry()
            } else {
                tokenRef?.let { SecureStore.remove(applicationContext, it) }
                Result.failure(errorData(error.message ?: "Upload failed"))
            }
        }
    }

    private fun createSession(baseUrl: String, token: String, files: List<LocalFile>): JSONObject {
        val body = JSONObject()
            .put("files", JSONArray().apply {
                files.forEach { put(JSONObject().put("name", it.name).put("size", it.size)) }
            })
            .put("context", inputData.getString(KEY_CONTEXT).orEmpty())
            .put("minimal_cuts", inputData.getBoolean(KEY_MINIMAL_CUTS, false))
            .put("burn_captions", inputData.getBoolean(KEY_BURN_CAPTIONS, true))
            .put("precaptioned", inputData.getBoolean(KEY_PRECAPTIONED, false))
            .put("remove_outro_seconds", inputData.getString(KEY_REMOVE_OUTRO) ?: "3")
            .put("caption_highlight_color", inputData.getString(KEY_HIGHLIGHT_COLOR).orEmpty())
        return postJson(baseUrl, token, "/api/mobile/uploads", body)
    }

    private fun queryFile(uri: Uri): LocalFile {
        var name = "video.mp4"
        var size = -1L
        applicationContext.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                name = cursor.string(OpenableColumns.DISPLAY_NAME) ?: name
                size = cursor.long(OpenableColumns.SIZE) ?: size
            }
        }
        if (size <= 0) {
            size = applicationContext.contentResolver.openAssetFileDescriptor(uri, "r")?.use {
                it.length
            } ?: -1L
        }
        if (size <= 0) throw IOException("Cannot determine size for $name")
        return LocalFile(uri, name, size)
    }

    private fun Cursor.string(column: String): String? {
        val index = getColumnIndex(column)
        return if (index >= 0 && !isNull(index)) getString(index) else null
    }

    private fun Cursor.long(column: String): Long? {
        val index = getColumnIndex(column)
        return if (index >= 0 && !isNull(index)) getLong(index) else null
    }

    private fun readChunk(uri: Uri, offset: Long, length: Int): ByteArray {
        val input = applicationContext.contentResolver.openInputStream(uri)
            ?: throw IOException("Cannot open selected video")
        input.use {
            var skipped = 0L
            while (skipped < offset) {
                val amount = it.skip(offset - skipped)
                if (amount <= 0) throw IOException("Cannot seek selected video")
                skipped += amount
            }
            val buffer = ByteArray(length)
            var read = 0
            while (read < length) {
                val amount = it.read(buffer, read, length - read)
                if (amount < 0) throw IOException("Video ended before expected size")
                read += amount
            }
            return buffer
        }
    }

    private fun putChunk(
        baseUrl: String,
        token: String,
        uploadId: String,
        index: Int,
        offset: Long,
        bytes: ByteArray,
    ) {
        val request = Request.Builder()
            .url("$baseUrl/api/mobile/uploads/$uploadId/files/$index")
            .header("Authorization", "Bearer $token")
            .header("Upload-Offset", offset.toString())
            .put(bytes.toRequestBody("application/octet-stream".toMediaType()))
            .build()
        executeJson(request)
    }

    private fun getJson(baseUrl: String, token: String, path: String): JSONObject {
        val request = Request.Builder()
            .url("$baseUrl$path")
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        return executeJson(request)
    }

    private fun postJson(baseUrl: String, token: String, path: String, body: JSONObject): JSONObject {
        val request = Request.Builder()
            .url("$baseUrl$path")
            .header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        return executeJson(request)
    }

    private fun executeJson(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                // 409 (offset resync / transient conflict) and 5xx are retryable;
                // other 4xx are terminal and surfaced with the server message.
                if (response.code == 409 || response.code in 500..599) {
                    throw IOException("Retryable server response ${response.code}")
                }
                throw TerminalUploadException(
                    extractDetail(text) ?: "Request failed ${response.code}",
                )
            }
            return JSONObject(text)
        }
    }

    private fun extractDetail(text: String): String? = runCatching {
        when (val detail = JSONObject(text).opt("detail")) {
            is String -> detail
            is JSONObject -> detail.optString("message").ifBlank { detail.toString() }
            else -> null
        }
    }.getOrNull()?.takeIf { it.isNotBlank() }

    private class TerminalUploadException(message: String) : Exception(message)

    private fun createForegroundInfo(progress: Int, text: String): ForegroundInfo {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Video uploads",
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("ShortGen")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(100, progress, progress == 0)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    private fun errorData(message: String) =
        Data.Builder().putString(KEY_ERROR, message).build()

    private fun enqueueJobMonitor(baseUrl: String, tokenRef: String, jobId: String) {
        val request = OneTimeWorkRequestBuilder<JobMonitorWorker>()
            .setInputData(
                Data.Builder()
                    .putString(JobMonitorWorker.KEY_BASE_URL, baseUrl)
                    .putString(JobMonitorWorker.KEY_TOKEN_REF, tokenRef)
                    .putString(JobMonitorWorker.KEY_JOB_ID, jobId)
                    .build(),
            )
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.LINEAR, 15, TimeUnit.SECONDS)
            .addTag(JobMonitorWorker.WORK_TAG)
            .build()
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            "shortgen-job-monitor-$jobId",
            ExistingWorkPolicy.REPLACE,
            request,
        )
    }

    private data class LocalFile(val uri: Uri, val name: String, val size: Long)

    companion object {
        const val PREFERENCES = "shortgen"
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN = "token"
        const val KEY_TOKEN_REF = "token_ref"
        const val KEY_URIS = "uris"
        const val KEY_CONTEXT = "context"
        const val KEY_MINIMAL_CUTS = "minimal_cuts"
        const val KEY_BURN_CAPTIONS = "burn_captions"
        const val KEY_PRECAPTIONED = "precaptioned"
        const val KEY_REMOVE_OUTRO = "remove_outro"
        const val KEY_HIGHLIGHT_COLOR = "highlight_color"
        const val KEY_PROGRESS = "progress"
        const val KEY_JOB_ID = "job_id"
        const val KEY_JOB_URL = "job_url"
        const val KEY_ERROR = "error"

        private const val CHANNEL_ID = "shortgen_uploads"
        private const val NOTIFICATION_ID = 4102
        private const val DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
        private const val MAX_RETRIES = 8
    }
}
