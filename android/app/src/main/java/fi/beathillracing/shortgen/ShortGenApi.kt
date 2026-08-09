package fi.beathillracing.shortgen

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class JobSummary(
    val id: String,
    val status: String,
    val filename: String,
    val createdAt: String?,
    val currentStep: String?,
    val error: String?,
    val progress: Int,
)

data class ThumbnailCandidate(
    val index: Int,
    val timestamp: Double?,
    val path: String,
)

data class PostedPlatforms(
    val youtube: Boolean,
    val instagram: Boolean,
    val facebook: Boolean,
    val tiktok: Boolean,
)

data class AppUpdate(
    val versionCode: Int,
    val versionName: String,
    val downloadUrl: String,
    val sha256: String,
    val missedReleases: List<AppRelease>,
)

data class AppRelease(
    val versionCode: Int,
    val versionName: String,
    val notes: String,
)

data class AccountUsage(
    val used: Int,
    val limit: Int?,
    val remaining: Int?,
)

data class AccountStatus(
    val accountId: String,
    val plan: String,
    val subscriptionStatus: String,
    val email: String?,
    val displayName: String?,
    val googleLinked: Boolean,
    val publishingEnabled: Boolean,
    val usage: AccountUsage,
)

data class PlatformConnection(
    val connected: Boolean,
    val label: String?,
    val selectedId: String?,
    val options: List<PlatformOption>,
    val needsReconnect: Boolean,
)

data class PlatformOption(
    val id: String,
    val label: String,
)

data class CaptionLine(
    val index: Int,
    val start: Double,
    val text: String,
)

data class JobDetail(
    val summary: JobSummary,
    val selectedThumbnailIndex: Int,
    val titleFi: String,
    val titleEn: String,
    val descriptionFi: String,
    val descriptionEn: String,
    val thumbnailTextFi: String,
    val thumbnailTextEn: String,
    val hashtags: List<String>,
    val candidates: List<ThumbnailCandidate>,
    val media: Map<String, String>,
    val posted: PostedPlatforms,
    val publishStatus: JSONObject,
    val hasVideo: Boolean,
    val hasThumbnail: Boolean,
    val publishingEnabled: Boolean,
)

class ShortGenApi(
    private val baseUrl: String,
    private val token: String,
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(5, TimeUnit.MINUTES)
        .build()

    suspend fun listJobs(): List<JobSummary> = withContext(Dispatchers.IO) {
        val root = requestJson("GET", "/api/mobile/jobs?limit=50")
        root.getJSONArray("jobs").objects().map(::parseSummary)
    }

    suspend fun getAppUpdate(installedVersionCode: Int): AppUpdate = withContext(Dispatchers.IO) {
        val item = requestJson(
            "GET",
            "/api/mobile/app-update?installed_version_code=$installedVersionCode",
        )
        AppUpdate(
            versionCode = item.getInt("version_code"),
            versionName = item.getString("version_name"),
            downloadUrl = item.getString("download_url"),
            sha256 = item.getString("sha256"),
            missedReleases = item.optJSONArray("missed_releases")
                ?.objects()
                ?.map {
                    AppRelease(
                        versionCode = it.getInt("version_code"),
                        versionName = it.getString("version_name"),
                        notes = it.getString("notes"),
                    )
                }
                .orEmpty(),
        )
    }

    suspend fun getJob(jobId: String): JobDetail = withContext(Dispatchers.IO) {
        parseDetail(requestJson("GET", "/api/mobile/jobs/$jobId"))
    }

    suspend fun getAccount(): AccountStatus = withContext(Dispatchers.IO) {
        parseAccount(requestJson("GET", "/api/mobile/account"))
    }

    suspend fun linkGoogle(credential: String): AccountStatus = withContext(Dispatchers.IO) {
        parseAccount(
            requestJson(
                "POST",
                "/api/mobile/auth/google",
                JSONObject().put("credential", credential),
            ),
        )
    }

    suspend fun getConnections(): Map<String, PlatformConnection> =
        withContext(Dispatchers.IO) {
            val root = requestJson("GET", "/api/mobile/connections")
            val items = root.getJSONObject("connections")
            items.keys().asSequence().associateWith { provider ->
                val item = items.getJSONObject(provider)
                val metadata = item.optJSONObject("metadata") ?: JSONObject()
                PlatformConnection(
                    connected = item.optBoolean("connected"),
                    label = item.nullableString("label"),
                    selectedId = metadata.nullableString("selected_page_id"),
                    options = metadata.optJSONArray("pages")
                        ?.objects()
                        ?.mapNotNull { page ->
                            val id = page.nullableString("id") ?: return@mapNotNull null
                            val name = page.nullableString("name") ?: "Facebook Page"
                            PlatformOption(
                                id = id,
                                label = name,
                            )
                        }
                        .orEmpty(),
                    needsReconnect = metadata.optBoolean("needs_reconnect"),
                )
            }
        }

    suspend fun startConnection(provider: String): String = withContext(Dispatchers.IO) {
        requestJson("POST", "/api/mobile/connections/$provider/auth")
            .getString("authorization_url")
    }

    suspend fun disconnect(provider: String) = withContext(Dispatchers.IO) {
        requestJson("DELETE", "/api/mobile/connections/$provider")
    }

    suspend fun selectFacebookPage(pageId: String) = withContext(Dispatchers.IO) {
        requestJson(
            "POST",
            "/api/mobile/connections/facebook/page",
            JSONObject().put("page_id", pageId),
        )
    }

    suspend fun verifySubscription(purchaseToken: String): AccountStatus =
        withContext(Dispatchers.IO) {
            parseAccount(
                requestJson(
                    "POST",
                    "/api/mobile/billing/verify",
                    JSONObject().put("purchase_token", purchaseToken),
                ),
            )
        }

    suspend fun deleteAccount() = withContext(Dispatchers.IO) {
        requestJson("DELETE", "/api/mobile/account")
    }

    suspend fun deleteJob(jobId: String) = withContext(Dispatchers.IO) {
        requestJson("DELETE", "/api/mobile/jobs/$jobId")
    }

    suspend fun retryJob(jobId: String) = withContext(Dispatchers.IO) {
        requestJson("POST", "/api/mobile/jobs/$jobId/retry")
    }

    suspend fun getPrefs(): Map<String, String> = withContext(Dispatchers.IO) {
        val resp = runCatching { requestJson("GET", "/api/mobile/prefs") }.getOrNull()
            ?: return@withContext emptyMap()
        val out = mutableMapOf<String, String>()
        val keys = resp.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            out[k] = resp.optString(k)
        }
        out
    }

    suspend fun putPrefs(prefs: Map<String, String>) = withContext(Dispatchers.IO) {
        val body = JSONObject()
        prefs.forEach { (k, v) -> body.put(k, v) }
        runCatching { requestJson("PUT", "/api/mobile/prefs", body) }
        Unit
    }

    suspend fun updateMetadata(jobId: String, language: String, title: String, description: String) =
        withContext(Dispatchers.IO) {
            requestJson(
                "PATCH",
                "/api/mobile/jobs/$jobId",
                JSONObject()
                    .put("language", language)
                    .put("title", title)
                    .put("description", description),
            )
        }

    suspend fun getCaptions(jobId: String): List<CaptionLine> = withContext(Dispatchers.IO) {
        val root = requestJson("GET", "/api/mobile/jobs/$jobId/captions")
        val lines = root.optJSONArray("lines") ?: return@withContext emptyList()
        (0 until lines.length()).map { index ->
            val line = lines.getJSONObject(index)
            CaptionLine(
                index = line.getInt("index"),
                start = line.optDouble("start", 0.0),
                text = line.optString("text", ""),
            )
        }
    }

    suspend fun updateCaption(jobId: String, index: Int, text: String) =
        withContext(Dispatchers.IO) {
            requestJson(
                "PUT",
                "/api/mobile/jobs/$jobId/captions",
                JSONObject().put(
                    "lines",
                    JSONArray().put(JSONObject().put("index", index).put("text", text)),
                ),
            )
            Unit
        }

    suspend fun approveCaptions(jobId: String) = withContext(Dispatchers.IO) {
        requestJson("POST", "/api/mobile/jobs/$jobId/captions/approve")
        Unit
    }

    suspend fun continueJob(
        jobId: String,
        thumbnailIndex: Int,
        textFi: String,
        textEn: String,
        thumbnailTextColor: String,
    ) = withContext(Dispatchers.IO) {
        requestJson(
            "POST",
            "/api/mobile/jobs/$jobId/continue",
            JSONObject()
                .put("thumbnail_index", thumbnailIndex)
                .put("text_fi", textFi.ifBlank { JSONObject.NULL })
                .put("text_en", textEn.ifBlank { JSONObject.NULL })
                .put("thumbnail_text_color", thumbnailTextColor.ifBlank { JSONObject.NULL }),
        )
    }

    suspend fun applyThumbnail(
        jobId: String,
        thumbnailIndex: Int,
        textFi: String,
        textEn: String,
        thumbnailTextColor: String,
    ) = withContext(Dispatchers.IO) {
        requestJson(
            "POST",
            "/api/mobile/jobs/$jobId/thumbnail",
            JSONObject()
                .put("index", thumbnailIndex)
                .put("text_fi", textFi.ifBlank { JSONObject.NULL })
                .put("text_en", textEn.ifBlank { JSONObject.NULL })
                .put("thumbnail_text_color", thumbnailTextColor.ifBlank { JSONObject.NULL }),
        )
    }

    suspend fun publish(
        jobId: String,
        platforms: List<String>,
        language: String,
        thumbnail: String,
        contentType: String,
    ) = withContext(Dispatchers.IO) {
        requestJson(
            "POST",
            "/api/mobile/jobs/$jobId/publish",
            JSONObject()
                .put("platforms", JSONArray(platforms))
                .put("language", language)
                .put("thumbnail", thumbnail)
                .put("content_type", contentType),
        )
    }

    suspend fun loadBytes(path: String): ByteArray = withContext(Dispatchers.IO) {
        val request = authenticatedRequest(path).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Media request failed ${response.code}")
            response.body?.bytes() ?: error("Empty media response")
        }
    }

    fun absoluteUrl(path: String): String =
        if (path.startsWith("http")) path else "$baseUrl$path"

    fun authHeaders(): Map<String, String> = mapOf("Authorization" to "Bearer $token")

    private fun requestJson(method: String, path: String, body: JSONObject? = null): JSONObject {
        val builder = authenticatedRequest(path)
        val requestBody = body?.toString()?.toRequestBody(JSON_MEDIA_TYPE)
        when (method) {
            "GET" -> builder.get()
            "POST" -> builder.post(requestBody ?: EMPTY_JSON)
            "PATCH" -> builder.patch(requestBody ?: EMPTY_JSON)
            "PUT" -> builder.put(requestBody ?: EMPTY_JSON)
            "DELETE" -> builder.delete(requestBody)
            else -> error("Unsupported method")
        }
        client.newCall(builder.build()).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val message = runCatching {
                    JSONObject(text).opt("detail")?.toString()
                }.getOrNull() ?: text
                error(message.ifBlank { "Request failed ${response.code}" })
            }
            return JSONObject(text)
        }
    }

    private fun authenticatedRequest(path: String) = Request.Builder()
        .url(absoluteUrl(path))
        .header("Authorization", "Bearer $token")

    private fun parseSummary(item: JSONObject): JobSummary {
        val progress = item.optJSONObject("progress")
        return JobSummary(
            id = item.getString("id"),
            status = item.optString("status", "unknown"),
            filename = item.optString("original_filename", "Video"),
            createdAt = item.nullableString("created_at"),
            currentStep = item.nullableString("current_step") ?: progress?.nullableString("step"),
            error = item.nullableString("error_message"),
            progress = progress?.optInt("percent", 0) ?: 0,
        )
    }

    private fun parseAccount(item: JSONObject): AccountStatus {
        val usage = item.optJSONObject("usage") ?: JSONObject()
        return AccountStatus(
            accountId = item.optString("account_id"),
            plan = item.optString("plan", "free"),
            subscriptionStatus = item.optString("subscription_status", "free"),
            email = item.nullableString("email"),
            displayName = item.nullableString("display_name"),
            googleLinked = item.optBoolean("google_linked"),
            publishingEnabled = item.optBoolean("publishing_enabled"),
            usage = AccountUsage(
                used = usage.optInt("jobs_used", 0),
                limit = if (usage.isNull("jobs_limit")) null else usage.optInt("jobs_limit"),
                remaining = if (usage.isNull("jobs_remaining")) null else usage.optInt("jobs_remaining"),
            ),
        )
    }

    private fun parseDetail(item: JSONObject): JobDetail {
        val candidates = item.optJSONArray("thumbnail_candidates")
            ?.objects()
            ?.map {
                ThumbnailCandidate(
                    index = it.getInt("index"),
                    timestamp = if (it.isNull("timestamp")) null else it.optDouble("timestamp"),
                    path = it.getString("url"),
                )
            }
            .orEmpty()
        val mediaObject = item.optJSONObject("media") ?: JSONObject()
        val media = mediaObject.keys().asSequence().associateWith { mediaObject.getString(it) }
        val posted = item.optJSONObject("posted") ?: JSONObject()
        return JobDetail(
            summary = parseSummary(item),
            selectedThumbnailIndex = item.optInt("selected_thumbnail_index", 1),
            titleFi = item.optString("title_fi"),
            titleEn = item.optString("title_en"),
            descriptionFi = item.optString("description_fi"),
            descriptionEn = item.optString("description_en"),
            thumbnailTextFi = item.optString("thumbnail_text_fi"),
            thumbnailTextEn = item.optString("thumbnail_text_en"),
            hashtags = item.optJSONArray("hashtags")
                ?.let { array -> (0 until array.length()).map { array.getString(it) } }
                .orEmpty(),
            candidates = candidates,
            media = media,
            posted = PostedPlatforms(
                youtube = posted.optBoolean("youtube"),
                instagram = posted.optBoolean("instagram"),
                facebook = posted.optBoolean("facebook"),
                tiktok = posted.optBoolean("tiktok"),
            ),
            publishStatus = item.optJSONObject("publish_status") ?: JSONObject().put("status", "idle"),
            hasVideo = item.optBoolean("has_video"),
            hasThumbnail = item.optBoolean("has_thumbnail"),
            publishingEnabled = item.optBoolean("publishing_enabled"),
        )
    }

    private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }

    private fun JSONObject.nullableString(key: String): String? =
        if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json".toMediaType()
        private val EMPTY_JSON = "{}".toRequestBody(JSON_MEDIA_TYPE)
    }
}
