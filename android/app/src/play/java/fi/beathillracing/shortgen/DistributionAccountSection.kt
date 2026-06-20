package fi.beathillracing.shortgen

import android.app.Activity
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

private const val PRO_PRODUCT_ID = "beathill_studio_pro"
private const val SAVED_ACCOUNTS_KEY = "saved_google_accounts"

private data class SavedAccount(
    val accountId: String,
    val label: String,
    val email: String?,
    val token: String,
)

@Composable
fun DistributionAccountSection(
    server: String,
    token: String,
    preferences: SharedPreferences,
    onAccountChanged: () -> Unit,
) {
    if (token.isBlank() || !server.startsWith("https://")) return

    val context = LocalContext.current
    val activity = context as Activity
    val scope = rememberCoroutineScope()
    val api = remember(server, token) { ShortGenApi(server, token) }
    val credentialManager = remember { CredentialManager.create(context) }
    var account by remember { mutableStateOf<AccountStatus?>(null) }
    var connections by remember { mutableStateOf<Map<String, PlatformConnection>>(emptyMap()) }
    var error by remember { mutableStateOf<String?>(null) }
    var product by remember { mutableStateOf<ProductDetails?>(null) }
    var deleteConfirm by remember { mutableStateOf(false) }
    var addingAccount by remember { mutableStateOf(false) }
    var savedAccounts by remember {
        mutableStateOf(loadSavedAccounts(preferences))
    }

    fun rememberAccount(status: AccountStatus, accountToken: String) {
        if (!status.googleLinked || status.accountId.isBlank()) return
        val saved = SavedAccount(
            accountId = status.accountId,
            label = status.displayName ?: status.email ?: "Google account",
            email = status.email,
            token = accountToken,
        )
        savedAccounts = (savedAccounts.filterNot { it.accountId == saved.accountId } + saved)
            .sortedBy { it.label.lowercase() }
        saveAccounts(preferences, savedAccounts)
    }

    fun refresh() {
        scope.launch {
            runCatching { api.getAccount() }
                .onSuccess {
                    account = it
                    connections = if (it.publishingEnabled) {
                        api.getConnections()
                    } else {
                        emptyMap()
                    }
                    rememberAccount(it, token)
                    error = null
                }
                .onFailure { error = it.message }
        }
    }

    fun connect(provider: String) {
        scope.launch {
            runCatching { api.startConnection(provider) }
                .onSuccess {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it)))
                    error = null
                }
                .onFailure { error = it.message }
        }
    }

    fun disconnect(provider: String) {
        scope.launch {
            runCatching { api.disconnect(provider) }
                .onSuccess { refresh() }
                .onFailure { error = it.message }
        }
    }

    fun selectFacebookPage(pageId: String) {
        scope.launch {
            runCatching { api.selectFacebookPage(pageId) }
                .onSuccess { refresh() }
                .onFailure { error = it.message }
        }
    }

    fun verifyPurchase(purchase: Purchase) {
        scope.launch {
            runCatching { api.verifySubscription(purchase.purchaseToken) }
                .onSuccess { status ->
                    account = status
                    error = null
                    // Acknowledge only after the server confirms the purchase, so a
                    // failed verification leaves Google's auto-refund window intact.
                    if (!purchase.isAcknowledged) {
                        val params = AcknowledgePurchaseParams.newBuilder()
                            .setPurchaseToken(purchase.purchaseToken)
                            .build()
                        billingClientPlaceholder?.acknowledgePurchase(params) {}
                    }
                }
                .onFailure { error = it.message }
        }
    }

    val billingClient = remember {
        BillingClient.newBuilder(context)
            .setListener { result, purchases ->
                if (result.responseCode == BillingClient.BillingResponseCode.OK) {
                    purchases.orEmpty().forEach { purchase -> verifyPurchase(purchase) }
                }
            }
            .enablePendingPurchases(
                PendingPurchasesParams.newBuilder().enableOneTimeProducts().build(),
            )
            .build()
    }
    billingClientPlaceholder = billingClient

    DisposableEffect(billingClient) {
        billingClient.startConnection(object : BillingClientStateListener {
            override fun onBillingSetupFinished(result: BillingResult) {
                if (result.responseCode != BillingClient.BillingResponseCode.OK) return
                val params = QueryProductDetailsParams.newBuilder()
                    .setProductList(
                        listOf(
                            QueryProductDetailsParams.Product.newBuilder()
                                .setProductId(PRO_PRODUCT_ID)
                                .setProductType(BillingClient.ProductType.SUBS)
                                .build(),
                        ),
                    )
                    .build()
                billingClient.queryProductDetailsAsync(params) { _, response ->
                    product = response.productDetailsList.firstOrNull()
                }
                billingClient.queryPurchasesAsync(
                    QueryPurchasesParams.newBuilder()
                        .setProductType(BillingClient.ProductType.SUBS)
                        .build(),
                ) { result, purchases ->
                    if (result.responseCode == BillingClient.BillingResponseCode.OK) {
                        purchases.forEach { purchase -> verifyPurchase(purchase) }
                    }
                }
            }

            override fun onBillingServiceDisconnected() = Unit
        })
        onDispose {
            billingClient.endConnection()
            if (billingClientPlaceholder === billingClient) billingClientPlaceholder = null
        }
    }

    LaunchedEffect(api) { refresh() }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, api) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) refresh()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    fun linkGoogleCredential(credential: String) {
        scope.launch {
            runCatching { api.linkGoogle(credential) }
                .onSuccess {
                    account = it
                    rememberAccount(it, token)
                    error = null
                    refresh()
                }
                .onFailure { throwable -> error = throwable.message }
        }
    }

    fun addGoogleAccount(credential: String) {
        scope.launch {
            val newToken = newAccessToken()
            runCatching {
                registerInstallation(
                    server = server,
                    installationId = UUID.randomUUID().toString(),
                    accessToken = newToken,
                )
                ShortGenApi(server, newToken).linkGoogle(credential)
            }.onSuccess { status ->
                rememberAccount(status, newToken)
                preferences.edit { putString(UploadWorker.KEY_TOKEN, newToken) }
                addingAccount = false
                error = null
                onAccountChanged()
            }.onFailure {
                addingAccount = false
                error = it.message
            }
        }
    }

    suspend fun requestGoogleCredential(
        explicit: Boolean,
        authorizedOnly: Boolean = false,
        autoSelect: Boolean = false,
    ): String {
        val option = if (explicit) {
            GetSignInWithGoogleOption.Builder(BuildConfig.GOOGLE_WEB_CLIENT_ID).build()
        } else {
            GetGoogleIdOption.Builder()
                .setFilterByAuthorizedAccounts(authorizedOnly)
                .setAutoSelectEnabled(autoSelect)
                .setServerClientId(BuildConfig.GOOGLE_WEB_CLIENT_ID)
                .build()
        }
        val request = GetCredentialRequest.Builder()
            .addCredentialOption(option)
            .build()
        val credential = credentialManager.getCredential(activity, request).credential
        if (
            credential !is CustomCredential ||
            credential.type !in setOf(
                GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL,
                GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_SIWG_CREDENTIAL,
            )
        ) {
            error("Google did not return an ID token")
        }
        return GoogleIdTokenCredential.createFrom(credential.data).idToken
    }

    fun startGoogleSignIn(addAccount: Boolean) {
        addingAccount = addAccount
        scope.launch {
            runCatching { requestGoogleCredential(explicit = true) }
                .onSuccess {
                    if (addAccount) addGoogleAccount(it) else linkGoogleCredential(it)
                }
                .onFailure {
                    addingAccount = false
                    if (it !is GetCredentialCancellationException) {
                        error = it.message
                    }
                }
        }
    }

    LaunchedEffect(api, account?.googleLinked) {
        if (account?.googleLinked == false) {
            try {
                linkGoogleCredential(
                    requestGoogleCredential(
                        explicit = false,
                        authorizedOnly = true,
                        autoSelect = true,
                    ),
                )
            } catch (_: NoCredentialException) {
                // The explicit button remains available for first-time sign-in.
            } catch (exc: GetCredentialException) {
                error = exc.message
            }
        }
    }

    HorizontalDivider()
    Text("Account", style = MaterialTheme.typography.titleMedium)
    account?.let { status ->
        Text(status.displayName ?: status.email ?: "Private app account")
        Text(
            when (status.plan) {
                "pro" -> "Beathill Studio Pro"
                "unlimited" -> "Unlimited access"
                else -> "Beathill Studio Free"
            },
            color = MaterialTheme.colorScheme.primary,
        )
        if (status.usage.limit != null) {
            Text("${status.usage.remaining} of ${status.usage.limit} monthly processing jobs remaining")
        } else {
            Text("Unlimited processing while Pro is active")
        }

        if (!status.googleLinked) {
            OutlinedButton(
                onClick = { startGoogleSignIn(addAccount = false) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Link Google account") }
        } else {
            Text("Google account linked")
            Text("Saved accounts", style = MaterialTheme.typography.titleSmall)
            savedAccounts.forEach { saved ->
                OutlinedButton(
                    onClick = {
                        preferences.edit {
                            putString(UploadWorker.KEY_TOKEN, saved.token)
                        }
                        onAccountChanged()
                    },
                    enabled = saved.token != token,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        if (saved.token == token) {
                            "${saved.label} (current)"
                        } else {
                            saved.label
                        },
                    )
                }
            }
            OutlinedButton(
                onClick = { startGoogleSignIn(addAccount = true) },
                enabled = !addingAccount,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (addingAccount) "Opening Google..." else "Add Google account") }
        }

        if (!status.publishingEnabled) {
            Button(
                onClick = {
                    val details = product ?: return@Button
                    val offer = details.subscriptionOfferDetails?.firstOrNull() ?: return@Button
                    val productParams = BillingFlowParams.ProductDetailsParams.newBuilder()
                        .setProductDetails(details)
                        .setOfferToken(offer.offerToken)
                        .build()
                    billingClient.launchBillingFlow(
                        activity,
                        BillingFlowParams.newBuilder()
                            .setProductDetailsParamsList(listOf(productParams))
                            .build(),
                    )
                },
                enabled = product != null,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Upgrade to Pro") }
        }

        if (status.publishingEnabled) {
            HorizontalDivider()
            Text("Publishing accounts", style = MaterialTheme.typography.titleMedium)
            PlatformConnectionRow(
                label = "YouTube",
                connection = connections["youtube"],
                onConnect = { connect("youtube") },
                onDisconnect = { disconnect("youtube") },
            )
            PlatformConnectionRow(
                label = "Facebook",
                connection = connections["facebook"],
                onConnect = { connect("facebook") },
                onDisconnect = { disconnect("facebook") },
                onSelect = ::selectFacebookPage,
            )
            PlatformConnectionRow(
                label = "Instagram",
                connection = connections["instagram"],
                onConnect = { connect("instagram") },
                onDisconnect = { disconnect("instagram") },
            )
            PlatformConnectionRow(
                label = "TikTok",
                connection = connections["tiktok"],
                onConnect = { connect("tiktok") },
                onDisconnect = { disconnect("tiktok") },
            )
        }
    }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { refresh() }, modifier = Modifier.weight(1f)) {
            Text("Restore")
        }
        OutlinedButton(
            onClick = {
                context.startActivity(
                    Intent(
                        Intent.ACTION_VIEW,
                        Uri.parse(
                            "https://play.google.com/store/account/subscriptions" +
                                "?sku=$PRO_PRODUCT_ID&package=${BuildConfig.APPLICATION_ID}",
                        ),
                    ),
                )
            },
            modifier = Modifier.weight(1f),
        ) { Text("Manage") }
    }
    OutlinedButton(
        onClick = { deleteConfirm = true },
        modifier = Modifier.fillMaxWidth(),
    ) { Text("Delete account and data") }
    error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

    if (deleteConfirm) {
        AlertDialog(
            onDismissRequest = { deleteConfirm = false },
            title = { Text("Delete account and data?") },
            text = {
                Text(
                    "This permanently deletes your jobs and files. It does not cancel an active Google Play subscription.",
                )
            },
            confirmButton = {
                Button(onClick = {
                    scope.launch {
                        runCatching { api.deleteAccount() }
                            .onSuccess {
                                val deletedAccountId = account?.accountId
                                if (deletedAccountId != null) {
                                    savedAccounts = savedAccounts.filterNot {
                                        it.accountId == deletedAccountId
                                    }
                                    saveAccounts(preferences, savedAccounts)
                                }
                                preferences.edit {
                                    remove(UploadWorker.KEY_TOKEN)
                                    remove("installation_id")
                                }
                                deleteConfirm = false
                                onAccountChanged()
                            }
                            .onFailure { error = it.message }
                    }
                }) { Text("Delete") }
            },
            dismissButton = {
                OutlinedButton(onClick = { deleteConfirm = false }) { Text("Cancel") }
            },
        )
    }
}

private var billingClientPlaceholder: BillingClient? = null

private fun loadSavedAccounts(preferences: SharedPreferences): List<SavedAccount> {
    val raw = preferences.getString(SAVED_ACCOUNTS_KEY, null) ?: return emptyList()
    return runCatching {
        val items = JSONArray(raw)
        (0 until items.length()).mapNotNull { index ->
            val item = items.optJSONObject(index) ?: return@mapNotNull null
            val accountId = item.optString("account_id")
            val token = item.optString("token")
            if (accountId.isBlank() || token.isBlank()) return@mapNotNull null
            SavedAccount(
                accountId = accountId,
                label = item.optString("label", "Google account"),
                email = item.optString("email").takeIf { it.isNotBlank() },
                token = token,
            )
        }
    }.getOrDefault(emptyList())
}

private fun saveAccounts(
    preferences: SharedPreferences,
    accounts: List<SavedAccount>,
) {
    val items = JSONArray()
    accounts.forEach { account ->
        items.put(
            JSONObject()
                .put("account_id", account.accountId)
                .put("label", account.label)
                .put("email", account.email ?: JSONObject.NULL)
                .put("token", account.token),
        )
    }
    preferences.edit { putString(SAVED_ACCOUNTS_KEY, items.toString()) }
}

@Composable
private fun PlatformConnectionRow(
    label: String,
    connection: PlatformConnection?,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
    onSelect: ((String) -> Unit)? = null,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(label)
        if (connection?.connected == true) {
            Text(
                connection.label ?: "Connected",
                color = MaterialTheme.colorScheme.primary,
            )
            OutlinedButton(
                onClick = onDisconnect,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Disconnect") }
            if (connection.options.size > 1 && onSelect != null) {
                Text("Publishing destination")
                connection.options.forEach { option ->
                    OutlinedButton(
                        onClick = { onSelect(option.id) },
                        enabled = option.id != connection.selectedId,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            if (option.id == connection.selectedId) {
                                "${option.label} (selected)"
                            } else {
                                option.label
                            },
                        )
                    }
                }
            }
        } else {
            OutlinedButton(
                onClick = onConnect,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Connect") }
        }
    }
}
