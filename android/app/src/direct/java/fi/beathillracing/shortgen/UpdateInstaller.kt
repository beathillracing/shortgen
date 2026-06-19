package fi.beathillracing.shortgen

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

object UpdateInstaller {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    suspend fun download(
        context: Context,
        update: AppUpdate,
        onProgress: (Int) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        val directory = File(context.cacheDir, "updates").apply { mkdirs() }
        val target = File(directory, "shortgen-${update.versionCode}.apk")
        val temporary = File(directory, "${target.name}.part")
        temporary.delete()

        val request = Request.Builder().url(update.downloadUrl).build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Update download failed: ${response.code}")
            val body = response.body ?: error("Update download was empty")
            val total = body.contentLength()
            var downloaded = 0L
            body.byteStream().use { input ->
                temporary.outputStream().use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        downloaded += count
                        if (total > 0) {
                            onProgress(((downloaded * 100L) / total).toInt().coerceIn(0, 100))
                        }
                    }
                }
            }
        }

        val digest = temporary.inputStream().use { input ->
            val messageDigest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                messageDigest.update(buffer, 0, count)
            }
            messageDigest.digest().joinToString("") { "%02x".format(it) }
        }
        if (!digest.equals(update.sha256, ignoreCase = true)) {
            temporary.delete()
            error("Downloaded update failed verification")
        }
        if (target.exists()) target.delete()
        check(temporary.renameTo(target)) { "Could not store downloaded update" }
        target
    }

    fun installIntent(context: Context, apk: File): Intent {
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apk,
        )
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }

    fun unknownSourcesIntent(context: Context) =
        Intent(
            android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        )
}
