package fi.beathillracing.shortgen

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import com.google.firebase.messaging.FirebaseMessaging
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

@Composable
fun DistributionPushSetup(server: String, token: String) {
    LaunchedEffect(server, token) {
        if (token.isBlank() || !server.startsWith("https://")) return@LaunchedEffect
        val base = server.trimEnd('/')
        FirebaseMessaging.getInstance().token.addOnSuccessListener { fcm ->
            registerPushToken(base, token, fcm)
        }
    }
}

fun registerPushToken(server: String, token: String, fcmToken: String) {
    Thread {
        runCatching {
            val body = JSONObject().put("token", fcmToken).toString()
                .toRequestBody("application/json".toMediaType())
            val request = Request.Builder()
                .url("$server/api/mobile/fcm-token")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()
            OkHttpClient().newCall(request).execute().close()
        }
    }.start()
}
