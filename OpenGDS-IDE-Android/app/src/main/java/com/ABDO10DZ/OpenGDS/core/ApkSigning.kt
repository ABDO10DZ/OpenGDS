package com.ABDO10DZ.OpenGDS.core

import android.content.Context
import android.net.Uri

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.android.apksig.ApkSigner
import com.android.apksig.ApkVerifier
import java.io.File
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.Date
import javax.security.auth.x500.X500Principal

/** Signs exports with a persistent, app-local Android Keystore identity. */
object ApkSigning {
    private const val KEY_ALIAS = "opengds-local-apk-export-v1"

    fun sign(
        unsignedApk: File,
        signedApk: File,
        context: Context,
        mode: String = "local",
        keystoreUri: Uri? = null,
        keystorePassword: String? = null,
        keyAlias: String? = null,
        keyPassword: String? = null,
        minSdkVersion: Int = 1
    ) {
        val (privateKey, certificateChain) = when (mode) {
            "jks" -> loadExternalIdentity(
                context, keystoreUri, keystorePassword, keyAlias, keyPassword
            )
            else -> {
                val (key, certificate) = loadOrCreateSigningIdentity()
                key to listOf(certificate)
            }
        }
        signedApk.parentFile?.mkdirs()
        signedApk.delete()
        val signer = ApkSigner.SignerConfig.Builder(
            "OpenGDS",
            privateKey,
            certificateChain
        ).build()
        ApkSigner.Builder(listOf(signer))
            .setInputApk(unsignedApk)
            .setOutputApk(signedApk)
            .setMinSdkVersion(minSdkVersion.coerceAtLeast(1))
            .setV1SigningEnabled(true)
            .setV2SigningEnabled(true)
            .setV3SigningEnabled(true)
            .build()
            .sign()
        if (!signedApk.isFile || signedApk.length() == 0L) {
            throw IllegalStateException("APK signing completed without producing an output file")
        }
        // Split APK manifests commonly omit uses-sdk. Verify every split against the
        // base APK's minSdk (the same value passed to ApkSigner), rather than letting
        // ApkVerifier infer API 1 from a split manifest with no uses-sdk element.
        val verification = ApkVerifier.Builder(signedApk)
            .setMinCheckedPlatformVersion(minSdkVersion.coerceAtLeast(1))
            .build()
            .verify()
        if (!verification.isVerified) {
            // Result.errors contains only top-level issues. Scheme-specific failures can
            // live inside V1/V2/V3 signer records, so use getAllErrors() for diagnostics.
            val reasons = verification.getAllErrors().joinToString("; ") { it.toString() }
            val warnings = verification.warnings.joinToString("; ") { it.toString() }
            val schemes = buildList {
                if (verification.isVerifiedUsingV1Scheme) add("v1")
                if (verification.isVerifiedUsingV2Scheme) add("v2")
                if (verification.isVerifiedUsingV3Scheme) add("v3")
            }.ifEmpty { listOf("none") }.joinToString(",")
            val detail = buildString {
                append("APK signature verification failed for ${signedApk.name}; ")
                append("checked API ${minSdkVersion.coerceAtLeast(1)}+; verified schemes=$schemes")
                if (reasons.isNotBlank()) append("; errors=$reasons")
                if (warnings.isNotBlank()) append("; warnings=$warnings")
                if (reasons.isBlank() && warnings.isBlank()) {
                    append("; apksig returned isVerified=false without top-level errors; ")
                    append("v1 signers=${verification.v1SchemeSigners.size}, ")
                    append("v2 signers=${verification.v2SchemeSigners.size}, ")
                    append("v3 signers=${verification.v3SchemeSigners.size}")
                }
            }
            throw IllegalStateException(detail)
        }
    }

    private fun loadExternalIdentity(
        context: Context,
        uri: Uri?,
        storePassword: String?,
        requestedAlias: String?,
        requestedKeyPassword: String?
    ): Pair<PrivateKey, List<X509Certificate>> {
        val source = uri
            ?: throw IllegalStateException("Select a keystore file first")
        val storePass = storePassword?.toCharArray()
            ?: throw IllegalStateException("Enter the keystore password")

        var loaded: KeyStore? = null
        var loadedType: String? = null
        var lastError: Exception? = null
        for (type in listOf("PKCS12", "JKS")) {
            try {
                val candidate = KeyStore.getInstance(type)
                val input = context.contentResolver.openInputStream(source)
                    ?: throw IllegalStateException("Unable to open selected keystore")
                input.use { candidate.load(it, storePass) }
                loaded = candidate
                loadedType = type
                break
            } catch (error: Exception) {
                lastError = error
            }
        }
        val store = loaded ?: throw IllegalStateException(
            "Cannot load keystore as PKCS12 or JKS. Check the file and keystore password.",
            lastError
        )

        val aliases = mutableListOf<String>()
        val enumeration = store.aliases()
        while (enumeration.hasMoreElements()) aliases += enumeration.nextElement()

        val requested = requestedAlias?.trim()?.takeIf { it.isNotEmpty() }
        val alias = if (requested != null) {
            aliases.firstOrNull { it == requested }
                ?: aliases.firstOrNull { it.equals(requested, ignoreCase = true) }
                ?: throw IllegalStateException("Alias '$requested' was not found in the $loadedType keystore")
        } else {
            aliases.firstOrNull { candidate ->
                store.isKeyEntry(candidate) && store.getCertificate(candidate) is X509Certificate
            }
        } ?: throw IllegalStateException("No private-key certificate entry was found in the $loadedType keystore")

        if (!store.isKeyEntry(alias)) {
            throw IllegalStateException("Alias '$alias' is a certificate entry, not a private-key entry")
        }

        // PKCS12 files normally use the store password for the key, but some JKS files
        // have a separate key password (or an empty key password). Try the explicit value
        // first, then standard compatible alternatives without exposing any password.
        val passwordCandidates = listOfNotNull(
            requestedKeyPassword?.takeIf { it.isNotEmpty() },
            storePassword,
            ""
        ).distinct()
        var privateKey: PrivateKey? = null
        var keyError: Exception? = null
        for (password in passwordCandidates) {
            try {
                privateKey = store.getKey(alias, password.toCharArray()) as? PrivateKey
                if (privateKey != null) break
            } catch (error: Exception) {
                keyError = error
            }
        }
        val resolvedKey = privateKey ?: throw IllegalStateException(
            "Unable to unlock private key '$alias'. Check its key password (store type: $loadedType).",
            keyError
        )

        val leaf = store.getCertificate(alias) as? X509Certificate
            ?: throw IllegalStateException("No X.509 certificate found for alias '$alias'")
        val chain = store.getCertificateChain(alias)
            ?.mapNotNull { it as? X509Certificate }
            ?.takeIf { it.isNotEmpty() }
            ?: listOf(leaf)
        if (chain.first() != leaf) {
            throw IllegalStateException("Keystore certificate chain for '$alias' does not start with its signing certificate")
        }

        return resolvedKey to chain
    }

    private fun loadOrCreateSigningIdentity(): Pair<PrivateKey, X509Certificate> {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias(KEY_ALIAS)) {
            val now = System.currentTimeMillis()
            val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
            val spec = KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
            )
                .setKeySize(2048)
                .setDigests(KeyProperties.DIGEST_SHA256)
                .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                .setCertificateSubject(X500Principal("CN=OpenGDS Local Export, OU=0xbytecode, O=OpenGDS, C=DZ"))
                .setCertificateSerialNumber(BigInteger(160, SecureRandom()).abs().max(BigInteger.ONE))
                .setCertificateNotBefore(Date(now - 86_400_000L))
                .setCertificateNotAfter(Date(now + 25L * 365L * 24L * 60L * 60L * 1000L))
                .build()
            generator.initialize(spec)
            generator.generateKeyPair()
        }
        val key = store.getKey(KEY_ALIAS, null) as? PrivateKey
            ?: throw IllegalStateException("OpenGDS signing private key is unavailable")
        val certificate = store.getCertificate(KEY_ALIAS) as? X509Certificate
            ?: throw IllegalStateException("OpenGDS signing certificate is unavailable")
        return key to certificate
    }
}
