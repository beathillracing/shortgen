package fi.beathillracing.shortgen

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object SecureStore {
    private const val KEY_ALIAS = "beathill_studio_local_secrets"
    private const val PREFIX = "secure."
    private const val TRANSFORMATION = "AES/GCM/NoPadding"

    @Synchronized
    fun put(context: Context, key: String, value: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val payload = cipher.iv + encrypted
        preferences(context).edit()
            .putString(PREFIX + key, Base64.encodeToString(payload, Base64.NO_WRAP))
            .remove(key)
            .apply()
    }

    @Synchronized
    fun get(context: Context, key: String): String? {
        val preferences = preferences(context)
        val encoded = preferences.getString(PREFIX + key, null)
        if (encoded == null) {
            val legacy = preferences.getString(key, null) ?: return null
            put(context, key, legacy)
            return legacy
        }
        return runCatching {
            val payload = Base64.decode(encoded, Base64.NO_WRAP)
            require(payload.size > 12)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                secretKey(),
                GCMParameterSpec(128, payload.copyOfRange(0, 12)),
            )
            cipher.doFinal(payload.copyOfRange(12, payload.size)).toString(Charsets.UTF_8)
        }.getOrElse {
            preferences.edit().remove(PREFIX + key).apply()
            null
        }
    }

    @Synchronized
    fun remove(context: Context, key: String) {
        preferences(context).edit()
            .remove(PREFIX + key)
            .remove(key)
            .apply()
    }

    @Synchronized
    fun removePrefix(context: Context, keyPrefix: String) {
        val preferences = preferences(context)
        val editor = preferences.edit()
        preferences.all.keys
            .filter { it.startsWith(PREFIX + keyPrefix) || it.startsWith(keyPrefix) }
            .forEach(editor::remove)
        editor.apply()
    }

    private fun preferences(context: Context) =
        context.getSharedPreferences(UploadWorker.PREFERENCES, Context.MODE_PRIVATE)

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                        KEY_ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                    )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256)
                        .build(),
                )
            }
            .generateKey()
    }
}
