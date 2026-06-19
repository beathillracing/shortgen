package fi.beathillracing.shortgen

import android.app.Activity
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.gms.common.api.ApiException
import kotlinx.coroutines.launch

private const val PRO_PRODUCT_ID = "beathill_studio_pro"

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
    var account by remember { mutableStateOf<AccountStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var product by remember { mutableStateOf<ProductDetails?>(null) }
    var deleteConfirm by remember { mutableStateOf(false) }

    fun refresh() {
        scope.launch {
            runCatching { api.getAccount() }
                .onSuccess { account = it; error = null }
                .onFailure { error = it.message }
        }
    }

    fun verifyPurchase(purchaseToken: String) {
        scope.launch {
            runCatching { api.verifySubscription(purchaseToken) }
                .onSuccess { account = it; error = null }
                .onFailure { error = it.message }
        }
    }

    val billingClient = remember {
        BillingClient.newBuilder(context)
            .setListener { result, purchases ->
                if (result.responseCode == BillingClient.BillingResponseCode.OK) {
                    purchases.orEmpty().forEach { purchase ->
                        if (!purchase.isAcknowledged) {
                            val params = AcknowledgePurchaseParams.newBuilder()
                                .setPurchaseToken(purchase.purchaseToken)
                                .build()
                            billingClientPlaceholder?.acknowledgePurchase(params) {}
                        }
                        verifyPurchase(purchase.purchaseToken)
                    }
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
                        purchases.forEach { verifyPurchase(it.purchaseToken) }
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

    val googleOptions = remember {
        GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestEmail()
            .requestIdToken(BuildConfig.GOOGLE_WEB_CLIENT_ID)
            .build()
    }
    val googleClient = remember { GoogleSignIn.getClient(context, googleOptions) }
    val googleLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val credential = runCatching {
            GoogleSignIn.getSignedInAccountFromIntent(result.data)
                .getResult(ApiException::class.java)
                .idToken ?: error("Google did not return an ID token")
        }
        credential.onSuccess {
            scope.launch {
                runCatching { api.linkGoogle(it) }
                    .onSuccess { status -> account = status; error = null }
                    .onFailure { throwable -> error = throwable.message }
            }
        }.onFailure { error = it.message }
    }

    HorizontalDivider()
    Text("Account", style = MaterialTheme.typography.titleMedium)
    account?.let { status ->
        Text(status.displayName ?: status.email ?: "Private app account")
        Text(
            if (status.plan == "pro") "Beathill Studio Pro" else "Beathill Studio Free",
            color = MaterialTheme.colorScheme.primary,
        )
        if (status.usage.limit != null) {
            Text("${status.usage.remaining} of ${status.usage.limit} monthly processing jobs remaining")
        } else {
            Text("Unlimited processing while Pro is active")
        }

        if (!status.googleLinked) {
            OutlinedButton(
                onClick = { googleLauncher.launch(googleClient.signInIntent) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Link Google account") }
        } else {
            Text("Google account linked")
        }

        if (status.plan != "pro") {
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
