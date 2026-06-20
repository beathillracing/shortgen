package fi.beathillracing.shortgen

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class JobMonitorWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val baseUrl = inputData.getString(KEY_BASE_URL)?.trimEnd('/')
        val tokenRef = inputData.getString(KEY_TOKEN_REF)
        val jobId = inputData.getString(KEY_JOB_ID)
        val token = tokenRef?.let { SecureStore.get(applicationContext, it) }
        if (baseUrl.isNullOrBlank() || tokenRef.isNullOrBlank() ||
            jobId.isNullOrBlank() || token.isNullOrBlank()
        ) {
            tokenRef?.let { SecureStore.remove(applicationContext, it) }
            return@withContext Result.failure()
        }

        try {
            val request = Request.Builder()
                .url("$baseUrl/api/mobile/jobs/$jobId")
                .header("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (response.code in setOf(401, 403, 404)) {
                    SecureStore.remove(applicationContext, tokenRef)
                    return@withContext Result.failure()
                }
                if (!response.isSuccessful) {
                    throw IOException("Job status request failed ${response.code}")
                }
                val item = JSONObject(response.body?.string().orEmpty())
                when (item.optString("status")) {
                    "review", "completed" -> {
                        notifyResult(
                            title = "Video ready",
                            text = item.optString("original_filename", "Your video is ready"),
                            jobId = jobId,
                            failed = false,
                        )
                        SecureStore.remove(applicationContext, tokenRef)
                        Result.success()
                    }
                    "failed" -> {
                        notifyResult(
                            title = "Video processing failed",
                            text = item.optString("error_message", "Open Beathill Studio for details"),
                            jobId = jobId,
                            failed = true,
                        )
                        SecureStore.remove(applicationContext, tokenRef)
                        Result.failure()
                    }
                    else -> Result.retry()
                }
            }
        } catch (_: Exception) {
            Result.retry()
        }
    }

    private fun notifyResult(
        title: String,
        text: String,
        jobId: String,
        failed: Boolean,
    ) {
        if (
            android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                applicationContext,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Video processing",
                NotificationManager.IMPORTANCE_DEFAULT,
            ),
        )
        val intent = Intent(applicationContext, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_JOB_ID, jobId)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pendingIntent = PendingIntent.getActivity(
            applicationContext,
            jobId.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(
                if (failed) android.R.drawable.stat_notify_error
                else android.R.drawable.stat_sys_download_done,
            )
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()
        manager.notify(jobId.hashCode(), notification)
    }

    companion object {
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN_REF = "token_ref"
        const val KEY_JOB_ID = "job_id"
        const val WORK_TAG = "shortgen-account-work"
        private const val CHANNEL_ID = "shortgen_processing"
    }
}
