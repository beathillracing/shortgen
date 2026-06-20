package fi.beathillracing.shortgen

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class ShortGenMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val prefs = getSharedPreferences(UploadWorker.PREFERENCES, Context.MODE_PRIVATE)
        val server = (prefs.getString(UploadWorker.KEY_BASE_URL, DEFAULT_SERVER) ?: DEFAULT_SERVER).trimEnd('/')
        val authToken = SecureStore.get(applicationContext, UploadWorker.KEY_TOKEN).orEmpty()
        if (authToken.isBlank() || !server.startsWith("https://")) return
        registerPushToken(server, authToken, token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val jobId = data["job_id"] ?: return
        val title = data["title"] ?: "Beathill Studio"
        val body = data["body"].orEmpty()
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                "shortgen_processing",
                "Video processing",
                NotificationManager.IMPORTANCE_DEFAULT,
            ),
        )
        val intent = Intent(this, MainActivity::class.java)
            .putExtra(MainActivity.EXTRA_JOB_ID, jobId)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pending = PendingIntent.getActivity(
            this,
            jobId.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, "shortgen_processing")
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(title)
            .setContentText(body)
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        manager.notify(jobId.hashCode(), notification)
    }
}
