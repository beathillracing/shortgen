package fi.beathillracing.shortgen

import android.content.SharedPreferences
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.core.content.edit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID
import java.util.concurrent.TimeUnit

@Composable
fun DistributionAccountProvisioning(
    server: String,
    token: String,
    preferences: SharedPreferences,
    onProvisioned: () -> Unit,
) {
    LaunchedEffect(server, token) {
        if (!server.startsWith("https://") || token.isNotBlank()) {
            return@LaunchedEffect
        }

        val installationId = preferences.getString(KEY_INSTALLATION_ID, null)
            ?: UUID.randomUUID().toString().also {
                preferences.edit { putString(KEY_INSTALLATION_ID, it) }
            }
        val accessToken = preferences.getString(KEY_PENDING_ACCESS_TOKEN, null)
            ?: newAccessToken().also {
                preferences.edit { putString(KEY_PENDING_ACCESS_TOKEN, it) }
            }

        runCatching {
            registerInstallation(server.trimEnd('/'), installationId, accessToken)
        }.onSuccess {
            preferences.edit {
                putString(UploadWorker.KEY_TOKEN, accessToken)
                remove(KEY_PENDING_ACCESS_TOKEN)
            }
            onProvisioned()
        }
    }
}

internal suspend fun registerInstallation(
    server: String,
    installationId: String,
    accessToken: String,
) = withContext(Dispatchers.IO) {
    val body = JSONObject()
        .put("installation_id", installationId)
        .put("access_token", accessToken)
        .toString()
        .toRequestBody("application/json".toMediaType())
    val request = Request.Builder()
        .url("$server/api/mobile/register")
        .post(body)
        .build()
    OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()
        .newCall(request)
        .execute()
        .use { response ->
            check(response.isSuccessful) { "Account setup failed: ${response.code}" }
        }
}

internal fun newAccessToken(): String {
    val bytes = ByteArray(32)
    SecureRandom().nextBytes(bytes)
    return "bst_" + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
}

private const val KEY_INSTALLATION_ID = "installation_id"
private const val KEY_PENDING_ACCESS_TOKEN = "pending_access_token"
