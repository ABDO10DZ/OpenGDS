package com.ABDO10DZ.OpenGDS

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Network
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.ABDO10DZ.OpenGDS.core.BackendBridge
import com.ABDO10DZ.OpenGDS.core.CoreUpdateNotice
import com.ABDO10DZ.OpenGDS.core.FileDigests
import com.ABDO10DZ.OpenGDS.core.LogStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

class OpenGDSApplication : Application() {
    lateinit var backend: BackendBridge
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutableCoreUpdate = MutableStateFlow<CoreUpdateNotice?>(null)
    val coreUpdate = mutableCoreUpdate.asStateFlow()
    private val coreUpdateCheckStarted = AtomicBoolean(false)
    val cancelFlagFile: File by lazy { File(filesDir, "opengds-cancel.flag") }

    override fun onCreate() {
        super.onCreate()
        val backendDir = File(filesDir, "backend").apply { mkdirs() }
        val bundledScript = File(backendDir, "OpenGDS.py")
        if (!bundledScript.exists()) copyBundledBackend(bundledScript)

        backend = BackendBridge()
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            backend.setCancelFlagFile(cancelFlagFile.absolutePath)
            backend.configure(bundledScript.absolutePath)
            LogStore.app("Python runtime initialized; OpenGDS.py backend loaded (GDSC v101).")
            watchForInternetAndCheckCoreOnce()
        } catch (error: Exception) {
            LogStore.app("Backend initialization failed: ${error.message}", error)
        }
    }

    private fun copyBundledBackend(destination: File) {
        destination.parentFile?.mkdirs()
        assets.open("OpenGDS.py").use { input -> destination.outputStream().use { output -> input.copyTo(output) } }
    }

    private fun hasValidatedInternet(): Boolean {
        return try {
            val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val network = manager.activeNetwork ?: return false
            val capabilities = manager.getNetworkCapabilities(network) ?: return false
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        } catch (_: Exception) { false }
    }

    /** Waits for the first validated internet connection, then performs exactly one check per app process. */
    private fun watchForInternetAndCheckCoreOnce() {
        val manager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        var callback: ConnectivityManager.NetworkCallback? = null
        fun launchOnce() {
            if (hasValidatedInternet() && coreUpdateCheckStarted.compareAndSet(false, true)) {
                callback?.let { runCatching { manager.unregisterNetworkCallback(it) } }
                appScope.launch { checkForGitHubCoreUpdate() }
            }
        }
        launchOnce()
        if (coreUpdateCheckStarted.get()) return
        try {
            callback = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) { launchOnce() }
                override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                    if (capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                        capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) launchOnce()
                }
            }
            manager.registerDefaultNetworkCallback(callback!!)
        } catch (error: Exception) {
            LogStore.app("Unable to monitor internet availability for the optional core update check", error)
        }
    }

    /** Runs once per app process after validated internet becomes available. */
    private fun checkForGitHubCoreUpdate() {
        if (!hasValidatedInternet()) return
        val backendDir = File(filesDir, "backend").apply { mkdirs() }
        val candidate = File(backendDir, "OpenGDS.py.github.new")
        val temporary = File(backendDir, "OpenGDS.py.github.tmp")
        var connection: HttpURLConnection? = null
        try {
            connection = (URL(GITHUB_RAW_CORE_URL).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 8_000
                readTimeout = 12_000
                instanceFollowRedirects = true
                setRequestProperty("Accept", "text/plain")
                setRequestProperty("User-Agent", "OpenGDS-Android-Core-Updater")
            }
            connection.connect()
            if (connection.responseCode !in 200..299) throw IllegalStateException("GitHub returned HTTP ${connection.responseCode}")
            connection.inputStream.use { input ->
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(32 * 1024)
                    var total = 0L
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        if (total > MAX_BACKEND_BYTES) throw IllegalStateException("GitHub backend exceeds the 5 MiB safety limit")
                        output.write(buffer, 0, count)
                    }
                    output.fd.sync()
                }
            }
            val remoteHash = FileDigests.sha256(temporary)
            val active = File(backendDir, "OpenGDS.py")
            val localHash = if (active.isFile) FileDigests.sha256(active) else ""
            if (remoteHash == localHash) {
                temporary.delete()
                candidate.delete()
                LogStore.app("GitHub core check: OpenGDS.py is up to date ($remoteHash).")
                return
            }
            val validation = backend.validateCandidate(temporary.absolutePath)
            if (!validation.optBoolean("valid")) throw IllegalStateException("GitHub OpenGDS.py failed compatibility validation")
            if (candidate.exists() && !candidate.delete()) throw IllegalStateException("Unable to replace cached GitHub backend")
            if (!temporary.renameTo(candidate)) temporary.copyTo(candidate, overwrite = true).also { temporary.delete() }
            mutableCoreUpdate.value = CoreUpdateNotice(remoteHash, candidate.absolutePath)
            LogStore.app("GitHub core update available: SHA-256 ${remoteHash.take(16)}…")
        } catch (error: Exception) {
            temporary.delete()
            LogStore.app("GitHub core update check was unavailable; current backend retained", error)
        } finally {
            connection?.disconnect()
        }
    }

    /** Installs a pre-validated candidate, restoring the previous backend if activation fails. */
    fun installBackendCandidate(candidate: File): String {
        if (!candidate.isFile) throw IllegalStateException("Backend candidate is missing")
        val validation = backend.validateCandidate(candidate.absolutePath)
        if (!validation.optBoolean("valid")) throw IllegalArgumentException("Candidate is not a compatible GDSC v101 OpenGDS.py backend")

        val backendDir = File(filesDir, "backend").apply { mkdirs() }
        val active = File(backendDir, "OpenGDS.py")
        val backup = File(backendDir, "OpenGDS.py.previous")
        val staging = File(backendDir, "OpenGDS.py.installing")
        candidate.copyTo(staging, overwrite = true)
        backup.delete()
        if (active.exists() && !active.renameTo(backup)) {
            staging.delete()
            throw IllegalStateException("Unable to preserve the current backend")
        }
        try {
            if (!staging.renameTo(active)) throw IllegalStateException("Unable to activate the new backend")
            val loaded = backend.configure(active.absolutePath)
            backup.delete()
            mutableCoreUpdate.value = null
            LogStore.app("Backend activated successfully (${loaded.optString("api")}).")
            return loaded.optString("api", "GDSC v101")
        } catch (error: Exception) {
            active.delete()
            if (backup.exists()) {
                if (!backup.renameTo(active)) throw IllegalStateException("Backend activation failed and backup restoration also failed", error)
                backend.configure(active.absolutePath)
            }
            throw error
        } finally {
            staging.delete()
        }
    }

    fun resetBundledBackend(): String {
        val candidate = File(cacheDir, "OpenGDS.py.bundled-reset")
        try {
            copyBundledBackend(candidate)
            return installBackendCandidate(candidate)
        } finally {
            candidate.delete()
        }
    }

    fun dismissCoreUpdate() { mutableCoreUpdate.value = null }

    companion object {
        const val GITHUB_RAW_CORE_URL = "https://raw.githubusercontent.com/ABDO10DZ/OpenGDS/main/OpenGDS.py"
        private const val MAX_BACKEND_BYTES = 5L * 1024 * 1024
    }
}
