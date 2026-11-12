package com.ABDO10DZ.OpenGDS.core

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.zip.ZipFile

object LogStore {
    private val mutableEntries = MutableStateFlow<List<String>>(emptyList())
    val entries: StateFlow<List<String>> = mutableEntries

    fun snapshot(): List<String> = mutableEntries.value
    fun app(message: String, error: Throwable? = null) = add("APP", message, error)
    fun core(message: String, error: Throwable? = null) = add("CORE", message, error)

    @Synchronized
    private fun add(channel: String, message: String, error: Throwable?) {
        val suffix = error?.let { "\n${it.javaClass.simpleName}: ${it.message}" }.orEmpty()
        mutableEntries.value = (mutableEntries.value + "[${channel}] $message$suffix").takeLast(3000)
    }

    @Synchronized
    fun clear() { mutableEntries.value = emptyList() }
}

class BackendBridge {
    private val module: PyObject by lazy { Python.getInstance().getModule("opengds_bridge") }

    fun configure(scriptPath: String): JSONObject {
        val result = JSONObject(module.callAttr("configure_backend", scriptPath).toString())
        LogStore.core("Loaded backend: ${result.optString("path")}")
        return result
    }

    fun status(): JSONObject = JSONObject(module.callAttr("backend_status").toString())
    fun validateCandidate(path: String): JSONObject = JSONObject(module.callAttr("validate_backend", path).toString())
    fun setCancelFlagFile(path: String) { module.callAttr("set_cancel_flag_file", path) }
    fun info(path: String): String = module.callAttr("info", path).toString()
    fun decompile(path: String): String = module.callAttr("decompile", path).toString()
    fun validateGdc(path: String): JSONObject = JSONObject(module.callAttr("validate_gdc", path).toString())
    fun report(mode: String, path: String): String = module.callAttr("report", mode, path).toString()
    fun decompileAll(folder: String, force: Boolean, continueOnError: Boolean): JSONObject =
        JSONObject(module.callAttr("decompile_all", folder, force, continueOnError).toString())
    fun compileAll(folder: String, compressed: Boolean, tabSize: Int, force: Boolean, continueOnError: Boolean): JSONObject =
        JSONObject(module.callAttr("compile_all", folder, compressed, tabSize, force, continueOnError).toString())

    fun compile(source: String, output: String, compressed: Boolean, tabSize: Int, force: Boolean): JSONObject {
        return JSONObject(module.callAttr("compile_source", source, output, compressed, tabSize, force).toString())
    }
}

data class AppRecord(
    val label: String,
    val packageName: String,
    val versionName: String,
    val isSystem: Boolean,
    val isGodot: Boolean,
    val apkPaths: List<String>
)

data class ApkRecord(
    val name: String,
    val path: String,
    val isGodot: Boolean,
    val bytes: Long
)

data class ProjectFile(
    val file: File,
    val relativePath: String,
    val extension: String,
    val bytes: Long,
    val validGdc: Boolean = false
)

object SettingsStore {
    private const val PREFS = "opengds.settings"
    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    fun theme(context: Context) = prefs(context).getString("theme", "system") ?: "system"
    fun setTheme(context: Context, value: String) = prefs(context).edit().putString("theme", value).apply()
    fun showSystem(context: Context) = prefs(context).getBoolean("show_system", false)
    fun setShowSystem(context: Context, value: Boolean) = prefs(context).edit().putBoolean("show_system", value).apply()
    fun includeNonGodot(context: Context) = prefs(context).getBoolean("include_non_godot", false)
    fun setIncludeNonGodot(context: Context, value: Boolean) = prefs(context).edit().putBoolean("include_non_godot", value).apply()
    fun compressed(context: Context) = prefs(context).getBoolean("compressed", true)
    fun setCompressed(context: Context, value: Boolean) = prefs(context).edit().putBoolean("compressed", value).apply()
    fun tabSize(context: Context) = prefs(context).getInt("tab_size", 4).coerceIn(1, 8)
    fun setTabSize(context: Context, value: Int) = prefs(context).edit().putInt("tab_size", value.coerceIn(1, 8)).apply()
    fun overwrite(context: Context) = prefs(context).getBoolean("overwrite", false)
    fun setOverwrite(context: Context, value: Boolean) = prefs(context).edit().putBoolean("overwrite", value).apply()
    fun continueOnError(context: Context) = prefs(context).getBoolean("continue_on_error", true)
    fun setContinueOnError(context: Context, value: Boolean) = prefs(context).edit().putBoolean("continue_on_error", value).apply()
    fun outputTreeUri(context: Context): String? = prefs(context).getString("apk_output_tree_uri", null)
    fun setOutputTreeUri(context: Context, value: String) = prefs(context).edit().putString("apk_output_tree_uri", value).apply()
    fun alwaysUnsignedOutput(context: Context) = prefs(context).getBoolean("always_unsigned_output", false)
    fun setAlwaysUnsignedOutput(context: Context, value: Boolean) = prefs(context).edit().putBoolean("always_unsigned_output", value).apply()
    fun autoCleanupAfterRepack(context: Context) = prefs(context).getBoolean("auto_cleanup_after_repack", false)
    fun setAutoCleanupAfterRepack(context: Context, value: Boolean) = prefs(context).edit().putBoolean("auto_cleanup_after_repack", value).apply()
}

data class CoreUpdateNotice(val sha256: String, val candidatePath: String)

data class RecentWorkspaceEntry(val path: String, val selectedRelativePath: String? = null) {
    val file: File get() = File(path)
    val isAvailable: Boolean get() = file.isDirectory && File(file, "project").isDirectory
}

data class StorageUsage(
    val projectsBytes: Long = 0L,
    val importedApksBytes: Long = 0L,
    val cacheBytes: Long = 0L,
    val backendBytes: Long = 0L,
    val otherAppDataBytes: Long = 0L
) {
    val totalBytes: Long get() = projectsBytes + importedApksBytes + cacheBytes + backendBytes + otherAppDataBytes
}

/** Durable session metadata, recent-workspace history and a crash-safe editor draft journal. */
object SessionStore {
    private const val PREFS = "opengds.session"
    private const val MAX_RECENT_WORKSPACES = 12
    private const val RECENTS_KEY = "recent_workspaces_v2"
    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun activeWorkspace(context: Context): File? = prefs(context).getString("active_workspace", null)
        ?.let(::File)?.takeIf { it.isDirectory && File(it, "project").isDirectory }

    fun recentWorkspace(context: Context): File? = recentWorkspaces(context).firstOrNull { it.isAvailable }?.file
        ?: prefs(context).getString("recent_workspace", null)?.let(::File)?.takeIf { it.isDirectory && File(it, "project").isDirectory }

    fun recentWorkspaces(context: Context): List<RecentWorkspaceEntry> {
        val p = prefs(context)
        val raw = p.getString(RECENTS_KEY, null)
        if (raw == null) {
            val legacy = p.getString("recent_workspace", null) ?: return emptyList()
            return listOf(RecentWorkspaceEntry(legacy, p.getString("recent_selected_relative_path", null)))
        }
        return runCatching {
            val array = JSONArray(raw)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    val path = item.optString("path").takeIf(String::isNotBlank) ?: continue
                    add(RecentWorkspaceEntry(path, item.optString("selected", "").takeIf(String::isNotBlank)))
                }
            }.distinctBy { it.path }.take(MAX_RECENT_WORKSPACES)
        }.getOrElse {
            // Preserve the previous single-entry pointer if a damaged history JSON is encountered.
            val legacy = p.getString("recent_workspace", null)
            if (legacy.isNullOrBlank()) emptyList()
            else listOf(RecentWorkspaceEntry(legacy, p.getString("recent_selected_relative_path", null)))
        }
    }

    fun selectedRelativePath(context: Context): String? = prefs(context).getString("selected_relative_path", null)
    fun recentSelectedRelativePath(context: Context): String? = recentWorkspaces(context).firstOrNull()?.selectedRelativePath
        ?: prefs(context).getString("recent_selected_relative_path", null)

    @Synchronized
    private fun persistRecent(context: Context, entries: List<RecentWorkspaceEntry>) {
        val array = JSONArray()
        entries.distinctBy { it.path }.take(MAX_RECENT_WORKSPACES).forEach { entry ->
            array.put(JSONObject().put("path", entry.path).put("selected", entry.selectedRelativePath ?: ""))
        }
        prefs(context).edit().putString(RECENTS_KEY, array.toString()).commit()
    }

    @Synchronized
    private fun touchRecent(context: Context, workspace: File, selectedRelativePath: String?) {
        val path = workspace.canonicalPath
        val entries = recentWorkspaces(context).filterNot { it.path == path }
        persistRecent(context, listOf(RecentWorkspaceEntry(path, selectedRelativePath)) + entries)
    }

    @Synchronized
    fun removeRecentWorkspace(context: Context, path: String): List<RecentWorkspaceEntry> {
        val remaining = recentWorkspaces(context).filterNot { it.path == path }
        persistRecent(context, remaining)
        val p = prefs(context)
        val editor = p.edit()
        if (p.getString("recent_workspace", null) == path) {
            editor.putString("recent_workspace", remaining.firstOrNull()?.path)
            editor.putString("recent_selected_relative_path", remaining.firstOrNull()?.selectedRelativePath)
        }
        editor.commit()
        return remaining
    }

    fun saveWorkspace(context: Context, workspace: File, selectedRelativePath: String? = null) {
        val path = workspace.canonicalPath
        // Migrate the previous single recent entry before updating the legacy pointer.
        touchRecent(context, workspace, selectedRelativePath)
        prefs(context).edit()
            .putString("active_workspace", path)
            .putString("recent_workspace", path)
            .putString("selected_relative_path", selectedRelativePath)
            .putString("recent_selected_relative_path", selectedRelativePath)
            .commit()
    }

    fun saveSelection(context: Context, workspace: File, selectedRelativePath: String?) {
        touchRecent(context, workspace, selectedRelativePath)
        prefs(context).edit()
            .putString("active_workspace", workspace.canonicalPath)
            .putString("recent_workspace", workspace.canonicalPath)
            .putString("selected_relative_path", selectedRelativePath)
            .putString("recent_selected_relative_path", selectedRelativePath)
            .commit()
    }

    fun closeWorkspace(context: Context) {
        prefs(context).edit().remove("active_workspace").remove("selected_relative_path").commit()
        clearDraft(context)
    }

    @Synchronized
    fun clearAllWorkspaceReferences(context: Context) {
        prefs(context).edit()
            .remove("active_workspace")
            .remove("selected_relative_path")
            .remove("recent_workspace")
            .remove("recent_selected_relative_path")
            .remove(RECENTS_KEY)
            .commit()
        clearDraft(context)
    }

    fun clearInvalidWorkspace(context: Context) {
        prefs(context).edit().remove("active_workspace").remove("selected_relative_path").commit()
    }

    @Synchronized
    fun saveDraft(context: Context, workspace: File, relativePath: String, text: String) {
        val dir = File(context.filesDir, "session").apply { mkdirs() }
        val target = File(dir, "editor-draft.json")
        // Keep the workspace, selected path and text in one atomically replaced journal.
        // This prevents a process kill between writing the buffer and its metadata commit.
        val journal = JSONObject()
            .put("workspace", workspace.canonicalPath)
            .put("relativePath", relativePath)
            .put("text", text)
            .toString()
        AtomicFileWriter.writeText(target, journal)
    }

    @Synchronized
    fun readDraft(context: Context, workspace: File, relativePath: String): String? {
        val journal = File(context.filesDir, "session/editor-draft.json")
        if (!journal.isFile) return null
        return try {
            val saved = JSONObject(journal.readText(Charsets.UTF_8))
            if (saved.optString("workspace") != workspace.canonicalPath ||
                saved.optString("relativePath") != relativePath) null
            else saved.optString("text")
        } catch (_: Exception) {
            journal.delete()
            null
        }
    }

    @Synchronized
    fun clearDraft(context: Context) {
        File(context.filesDir, "session/editor-draft.json").delete()
        File(context.filesDir, "session/editor-draft.json.opengds-tmp").delete()
        File(context.filesDir, "session/editor-draft.txt").delete() // clean journals created by older app versions
        File(context.filesDir, "session/editor-draft.tmp").delete()
        File(context.filesDir, "session").listFiles()?.filter { it.name.startsWith("editor-draft-") && it.name.endsWith(".tmp") }?.forEach { it.delete() }
        prefs(context).edit().remove("draft_workspace").remove("draft_relative_path").commit()
    }
}

object AtomicFileWriter {
    /** Writes a same-directory temporary file, fsyncs it, then atomically replaces the target. */
    fun writeText(target: File, text: String, keepBackup: Boolean = false) {
        val parent = target.parentFile ?: throw IllegalArgumentException("Target has no parent directory")
        if (!parent.exists() && !parent.mkdirs()) throw IllegalStateException("Unable to create ${parent.absolutePath}")
        val temporary = File(parent, target.name + ".opengds-tmp")
        val backup = File(parent, target.name + ".bak")
        try {
            FileOutputStream(temporary).use { output ->
                output.write(text.toByteArray(Charsets.UTF_8))
                output.fd.sync()
            }
            if (keepBackup && target.isFile) {
                val backupTemp = File(parent, backup.name + ".copying")
                FileOutputStream(backupTemp).use { output ->
                    target.inputStream().buffered().use { it.copyTo(output, 64 * 1024) }
                    output.fd.sync()
                }
                try {
                    Files.move(backupTemp.toPath(), backup.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
                } catch (_: Exception) {
                    Files.move(backupTemp.toPath(), backup.toPath(), StandardCopyOption.REPLACE_EXISTING)
                }
            }
            try {
                Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            } catch (_: Exception) {
                Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        } finally {
            temporary.delete()
            File(parent, backup.name + ".copying").delete()
        }
    }
}

object FileDigests {
    fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}

object StorageCleanup {
    private val temporarySuffixes = listOf(".copying", ".importing", ".replacement", ".opengds-tmp")

    private fun bytesUnder(root: File): Long = if (root.exists()) {
        root.walkTopDown().filter { it.isFile }.sumOf { it.length() }
    } else 0L

    /** Reports the storage that matters to the user without changing any project data. */
    fun inspect(context: Context): StorageUsage {
        val projects = bytesUnder(ProjectWorkspace.workspaceRoot(context))
        val importedApks = bytesUnder(File(context.filesDir, "apks"))
        val cache = bytesUnder(context.cacheDir)
        val backend = bytesUnder(File(context.filesDir, "backend"))
        // Include databases, shared preferences, code cache and other app-private files too.
        val measuredPrivateData = bytesUnder(context.dataDir)
        val other = (measuredPrivateData - projects - importedApks - cache - backend).coerceAtLeast(0L)
        return StorageUsage(projects, importedApks, cache, backend, other)
    }

    /** Permanently deletes one workspace, only when it is a direct child of OpenGDS' workspace root. */
    fun deleteWorkspace(context: Context, path: String): Long {
        val root = ProjectWorkspace.workspaceRoot(context).canonicalFile
        val target = File(path).canonicalFile
        if (target == root || target.parentFile != root || !target.isDirectory) {
            throw IllegalArgumentException("The selected path is not an OpenGDS workspace directory")
        }
        val reclaimed = bytesUnder(target)
        if (!target.deleteRecursively()) throw IllegalStateException("Unable to completely delete ${target.name} from storage")
        return reclaimed
    }

    /** Explicit all-project deletion used only after a separate destructive confirmation. */
    fun deleteAllWorkspaces(context: Context): Long {
        val root = ProjectWorkspace.workspaceRoot(context)
        val reclaimed = bytesUnder(root)
        root.listFiles()?.forEach { child ->
            if (!child.deleteRecursively()) throw IllegalStateException("Unable to delete workspace data: ${child.name}")
        }
        root.mkdirs()
        return reclaimed
    }

    /** Deletes only the separately imported APK library, not APKs retained inside project workspaces. */
    fun deleteImportedApks(context: Context): Long {
        val root = File(context.filesDir, "apks")
        val reclaimed = bytesUnder(root)
        root.listFiles()?.forEach { child ->
            if (!child.deleteRecursively()) throw IllegalStateException("Unable to delete imported APK: ${child.name}")
        }
        root.mkdirs()
        return reclaimed
    }

    /** Removes only transient caches and abandoned operation files; preserves projects, APKs, backups and backend. */
    fun clean(context: Context): Long {
        var reclaimed = 0L
        fun removeTempFiles(root: File) {
            if (!root.exists()) return
            // Interrupted PCK extraction can leave a directory named *.importing;
            // remove the whole staging tree, not just files with temporary suffixes.
            root.walkTopDown()
                .filter { it.isDirectory && temporarySuffixes.any { suffix -> it.name.endsWith(suffix) } }
                .toList()
                .sortedByDescending { it.absolutePath.length }
                .forEach { directory ->
                    if (directory.exists()) {
                        val length = bytesUnder(directory)
                        if (directory.deleteRecursively()) reclaimed += length
                    }
                }
            root.walkTopDown().filter { it.isFile && temporarySuffixes.any { suffix -> it.name.endsWith(suffix) } }
                .toList().forEach { file ->
                    val length = file.length()
                    if (file.delete()) reclaimed += length
                }
        }
        // The session directory may contain a live editor recovery journal.
        // Preserve it entirely so cleanup cannot race the debounced autosave.
        removeTempFiles(File(context.filesDir, "workspaces"))
        val backendDir = File(context.filesDir, "backend")
        removeTempFiles(backendDir)
        listOf("OpenGDS.py.github.new", "OpenGDS.py.github.tmp", "OpenGDS.py.manual.new", "OpenGDS.py.installing")
            .map { File(backendDir, it) }
            .forEach { candidate ->
                val length = candidate.length()
                if (candidate.isFile && candidate.delete()) reclaimed += length
            }
        listOf(context.cacheDir, context.codeCacheDir).forEach { cacheRoot ->
            cacheRoot.listFiles()?.forEach { child ->
                val length = bytesUnder(child)
                if (child.isDirectory) {
                    if (child.deleteRecursively()) reclaimed += length
                } else if (child.delete()) {
                    reclaimed += length
                }
            }
        }
        File(context.filesDir, "opengds-cancel.flag").delete()
        return reclaimed
    }
}

object ApkInspector {
    fun isGodotApk(apk: File): Boolean {
        if (!apk.isFile) return false
        return try {
            ZipFile(apk).use { zip ->
                val entries = zip.entries()
                while (entries.hasMoreElements()) {
                    val entry = entries.nextElement()
                    val lower = entry.name.lowercase()
                    if (lower.endsWith(".gdc") || lower.endsWith("project.binary") ||
                        lower.contains("/libgodot_android.so") || lower.contains("/libgodot.so") ||
                        lower == "assets/.godot/exported/project.binary") return true
                    if (lower.endsWith(".pck")) {
                        val isPck = zip.getInputStream(entry).use { stream ->
                            val magic = ByteArray(4)
                            var count = 0
                            while (count < magic.size) {
                                val read = stream.read(magic, count, magic.size - count)
                                if (read < 0) break
                                count += read
                            }
                            count == 4 && magic.contentEquals(byteArrayOf(0x47, 0x44, 0x50, 0x43))
                        }
                        if (isPck) return true
                    }
                }
                false
            }
        } catch (_: Exception) { false }
    }
}

object FileIntake {
    fun displayName(context: Context, uri: Uri): String {
        var name: String? = null
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) name = it.getString(0)
        }
        return name ?: uri.lastPathSegment?.substringAfterLast('/') ?: "imported_file"
    }

    fun copyFile(source: File, destination: File, cancelFile: File? = null): File {
        if (!source.isFile) throw IllegalArgumentException("Source file is unavailable: ${source.name}")
        destination.parentFile?.mkdirs()
        val temporary = File(destination.parentFile, destination.name + ".copying")
        try {
            source.inputStream().buffered().use { input ->
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(128 * 1024)
                    while (true) {
                        if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                    }
                    output.fd.sync()
                }
            }
            if (destination.exists() && !destination.delete()) throw IllegalStateException("Unable to replace ${destination.name}")
            if (!temporary.renameTo(destination)) throw IllegalStateException("Unable to finish copying ${destination.name}")
            return destination
        } catch (error: Exception) {
            temporary.delete()
            throw error
        }
    }

    suspend fun copyUri(
        context: Context,
        uri: Uri,
        destination: File,
        maxBytes: Long = 512L * 1024 * 1024,
        cancelFile: File? = null
    ): File = withContext(Dispatchers.IO) {
        destination.parentFile?.mkdirs()
        val temporary = File(destination.parentFile, destination.name + ".copying")
        try {
            context.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(128 * 1024)
                    var total = 0L
                    while (true) {
                        if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        if (total > maxBytes) throw IllegalStateException("Selected file exceeds the ${formatBytes(maxBytes)} import limit")
                        output.write(buffer, 0, count)
                    }
                }
            } ?: throw IllegalStateException("Unable to open the selected document")
            if (destination.exists() && !destination.delete()) throw IllegalStateException("Unable to replace ${destination.name}")
            if (!temporary.renameTo(destination)) throw IllegalStateException("Unable to finish copying ${destination.name}")
            destination
        } catch (error: Exception) {
            temporary.delete()
            throw error
        }
    }
}

object ProjectWorkspace {
    private const val MAX_SINGLE_FILE = 512L * 1024 * 1024
    private const val MAX_TOTAL_BYTES = 2L * 1024 * 1024 * 1024

    fun workspaceRoot(context: Context) = File(context.filesDir, "workspaces")

    fun create(context: Context, label: String): File {
        val safe = label.replace(Regex("[^A-Za-z0-9._-]"), "_").take(48).ifBlank { "GodotProject" }
        val root = File(workspaceRoot(context), "${safe}_${System.currentTimeMillis()}")
        File(root, "project").mkdirs()
        return root
    }

    private fun checkCancelled(cancelFile: File?) {
        if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
    }

    fun importApk(apk: File, workspace: File, prefix: String = "", cancelFile: File? = null): Int {
        val project = File(workspace, "project").apply { mkdirs() }
        var extracted = 0
        var total = 0L
        ZipFile(apk).use { zip ->
            val entries = zip.entries()
            while (entries.hasMoreElements()) {
                checkCancelled(cancelFile)
                val entry = entries.nextElement()
                val rawName = entry.name.replace('\\', '/')
                if (rawName.startsWith('/') || rawName.split('/').any { it == ".." }) continue
                if (entry.isDirectory) continue
                if (entry.size > MAX_SINGLE_FILE || entry.size > 0 && total + entry.size > MAX_TOTAL_BYTES) continue
                val relative = if (prefix.isBlank()) rawName else "$prefix/$rawName"
                val destination = File(project, relative)
                val canonicalRoot = project.canonicalFile.toPath()
                val canonicalTarget = destination.canonicalFile.toPath()
                if (!canonicalTarget.startsWith(canonicalRoot)) continue
                destination.parentFile?.mkdirs()
                zip.getInputStream(entry).use { input ->
                    FileOutputStream(destination).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var copied = 0L
                        while (true) {
                            checkCancelled(cancelFile)
                            val read = input.read(buffer)
                            if (read < 0) break
                            copied += read
                            total += read
                            if (copied > MAX_SINGLE_FILE || total > MAX_TOTAL_BYTES) {
                                destination.delete()
                                throw IllegalStateException("APK expansion limit reached; import stopped safely")
                            }
                            output.write(buffer, 0, read)
                        }
                    }
                }
                extracted++
            }
        }
        return extracted
    }

    fun importInstalledApp(app: AppRecord, workspace: File, cancelFile: File? = null): Int {
        var total = 0
        app.apkPaths.forEachIndexed { index, path ->
            val source = File(path)
            if (source.exists()) {
                val prefix = if (index == 0) "" else "_splits/split_$index"
                checkCancelled(cancelFile)
                total += importApk(source, workspace, prefix, cancelFile)
                val sourceDir = File(workspace, "source").apply { mkdirs() }
                val saved = File(sourceDir, if (index == 0) "base.apk" else "split_$index.apk")
                FileIntake.copyFile(source, saved, cancelFile)
                if (index == 0) File(sourceDir, "base.name").writeText(app.label, Charsets.UTF_8)
            }
        }
        return total
    }

    fun listFiles(workspace: File, backend: BackendBridge): List<ProjectFile> {
        val root = File(workspace, "project")
        if (!root.exists()) return emptyList()
        return root.walkTopDown().filter { it.isFile }.mapNotNull { file ->
            val rel = file.relativeTo(root).invariantSeparatorsPath
            val ext = file.extension.lowercase()
            var validGdc = false
            if (ext == "gdc") {
                validGdc = try { backend.validateGdc(file.absolutePath).optBoolean("valid", false) }
                catch (error: Exception) { false }
            }
            ProjectFile(file, rel, ext, file.length(), validGdc)
        }.sortedWith(compareBy<ProjectFile>({ it.relativePath.count { c -> c == '/' } }, { it.relativePath.lowercase() })).toList()
    }
}

fun formatBytes(bytes: Long): String = when {
    bytes >= 1024L * 1024 * 1024 -> "%.2f GiB".format(bytes / (1024.0 * 1024 * 1024))
    bytes >= 1024L * 1024 -> "%.1f MiB".format(bytes / (1024.0 * 1024))
    bytes >= 1024 -> "%.1f KiB".format(bytes / 1024.0)
    else -> "$bytes B"
}
