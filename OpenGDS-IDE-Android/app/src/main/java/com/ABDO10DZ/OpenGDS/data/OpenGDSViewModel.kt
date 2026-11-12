package com.ABDO10DZ.OpenGDS.data

import android.app.Application
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.content.Intent
import android.content.ClipData
import android.net.Uri
import android.os.Build
import androidx.documentfile.provider.DocumentFile
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ABDO10DZ.OpenGDS.OpenGDSApplication
import com.ABDO10DZ.OpenGDS.core.ApkInspector
import com.ABDO10DZ.OpenGDS.core.AppRecord
import com.ABDO10DZ.OpenGDS.core.ApkRecord
import com.ABDO10DZ.OpenGDS.core.ApkRepacker
import com.ABDO10DZ.OpenGDS.core.AtomicFileWriter
import com.ABDO10DZ.OpenGDS.core.BackendBridge
import com.ABDO10DZ.OpenGDS.core.FileIntake
import com.ABDO10DZ.OpenGDS.core.GodotPckExtractor
import com.ABDO10DZ.OpenGDS.core.LogStore
import com.ABDO10DZ.OpenGDS.core.ProjectFile
import com.ABDO10DZ.OpenGDS.core.ProjectWorkspace
import com.ABDO10DZ.OpenGDS.core.RecentWorkspaceEntry
import com.ABDO10DZ.OpenGDS.core.SessionStore
import com.ABDO10DZ.OpenGDS.core.StorageCleanup
import com.ABDO10DZ.OpenGDS.core.StorageUsage
import com.ABDO10DZ.OpenGDS.core.CoreUpdateNotice
import com.ABDO10DZ.OpenGDS.core.SettingsStore
import com.ABDO10DZ.OpenGDS.core.SmaliToolchain
import com.ABDO10DZ.OpenGDS.core.formatBytes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

private const val MAX_TEXT_FILE = 8L * 1024 * 1024

enum class MainPage { PROJECTS, EDITOR, LOGS, SETTINGS }

data class OpenGDSState(
    val page: MainPage = MainPage.PROJECTS,
    val installedApps: List<AppRecord> = emptyList(),
    val importedApks: List<ApkRecord> = emptyList(),
    val workspace: File? = null,
    val projectFiles: List<ProjectFile> = emptyList(),
    val selectedFile: ProjectFile? = null,
    val editorText: String = "",
    val fileInfo: String = "",
    val editorDirty: Boolean = false,
    val editorJumpToLine: Int = 0,
    val editorJumpRequestId: Int = 0,
    val loading: Boolean = false,
    val canCancelOperation: Boolean = false,
    val coreUpdate: CoreUpdateNotice? = null,
    val recentWorkspace: File? = null,
    val recentWorkspaces: List<RecentWorkspaceEntry> = emptyList(),
    val status: String = "Ready",
    val error: String? = null,
    val showSystemApps: Boolean = false,
    val includeNonGodot: Boolean = false,
    val theme: String = "system",
    val compressed: Boolean = true,
    val tabSize: Int = 4,
    val overwrite: Boolean = false,
    val continueOnError: Boolean = true,
    val outputDirectoryConfigured: Boolean = false,
    val alwaysUnsignedOutput: Boolean = false,
    val autoCleanupAfterRepack: Boolean = false,
    val storageUsage: StorageUsage = StorageUsage()
)

class OpenGDSViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as OpenGDSApplication
    private val backend: BackendBridge get() = app.backend
    private val mutableState = MutableStateFlow(initialState())
    val state: StateFlow<OpenGDSState> = mutableState.asStateFlow()
    val logs: StateFlow<List<String>> = LogStore.entries
    private var draftSaveJob: Job? = null
    private val cancelFile: File get() = app.cancelFlagFile

    init {
        viewModelScope.launch {
            app.coreUpdate.collect { notice -> mutate { copy(coreUpdate = notice) } }
        }
        refreshStorageUsage()
        val resume = SessionStore.activeWorkspace(getApplication())
        if (resume != null) {
            mutate { copy(page = MainPage.EDITOR, workspace = resume, status = "Restoring last workspace…") }
            viewModelScope.launch { loadWorkspace(resume, SessionStore.selectedRelativePath(getApplication())?.let { File(File(resume, "project"), it).absolutePath }) }
        } else {
            SessionStore.clearInvalidWorkspace(getApplication())
        }
    }

    private fun initialState() = OpenGDSState(
        showSystemApps = SettingsStore.showSystem(getApplication()),
        includeNonGodot = SettingsStore.includeNonGodot(getApplication()),
        theme = SettingsStore.theme(getApplication()),
        compressed = SettingsStore.compressed(getApplication()),
        tabSize = SettingsStore.tabSize(getApplication()),
        overwrite = SettingsStore.overwrite(getApplication()),
        continueOnError = SettingsStore.continueOnError(getApplication()),
        outputDirectoryConfigured = SettingsStore.outputTreeUri(getApplication()) != null,
        alwaysUnsignedOutput = SettingsStore.alwaysUnsignedOutput(getApplication()),
        autoCleanupAfterRepack = SettingsStore.autoCleanupAfterRepack(getApplication()),
        recentWorkspace = SessionStore.recentWorkspace(getApplication()),
        recentWorkspaces = SessionStore.recentWorkspaces(getApplication())
    )

    fun navigate(page: MainPage) { mutate { copy(page = page) } }
    fun dismissError() { mutate { copy(error = null) } }

    private fun beginOperation(label: String, cancelable: Boolean = true) {
        cancelFile.delete()
        mutate { copy(loading = true, canCancelOperation = cancelable, status = label, error = null) }
    }

    private fun finishOperation() {
        cancelFile.delete()
        mutate { copy(loading = false, canCancelOperation = false) }
    }

    fun cancelOperation() {
        if (!mutableState.value.loading || !mutableState.value.canCancelOperation) return
        runCatching { cancelFile.writeText("cancel") }
        mutate { copy(canCancelOperation = false, status = "Cancellation requested · finishing the current safe step…") }
        LogStore.app("Cancellation requested by user.")
    }

    fun dismissCoreUpdate() {
        app.dismissCoreUpdate()
        mutate { copy(coreUpdate = null) }
    }

    fun installGitHubCoreUpdate() {
        val notice = mutableState.value.coreUpdate ?: return
        beginOperation("Validating and installing GitHub core update…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val api = app.installBackendCandidate(File(notice.candidatePath))
                withContext(Dispatchers.Main) { mutate { copy(coreUpdate = null, status = "GitHub core updated · $api") } }
                LogStore.app("GitHub OpenGDS.py update installed · SHA-256 ${notice.sha256}.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "GitHub core update failed", status = "Current backend retained") } }
                LogStore.app("GitHub core update failed; previous backend remains active", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    fun resetBackend() {
        beginOperation("Restoring bundled OpenGDS.py core…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val api = app.resetBundledBackend()
                withContext(Dispatchers.Main) { mutate { copy(status = "Bundled core restored · $api") } }
                LogStore.app("Bundled OpenGDS.py backend restored and validated.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Core reset failed", status = "Backend unchanged") } }
                LogStore.app("Bundled core reset failed", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    fun refreshStorageUsage() {
        viewModelScope.launch(Dispatchers.IO) {
            val usage = StorageCleanup.inspect(getApplication())
            withContext(Dispatchers.Main) { mutate { copy(storageUsage = usage) } }
        }
    }

    fun cleanStorage() {
        beginOperation("Cleaning temporary OpenGDS storage…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val reclaimed = StorageCleanup.clean(getApplication())
                val usage = StorageCleanup.inspect(getApplication())
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            storageUsage = usage,
                            status = "Temporary cleanup complete · ${formatBytes(reclaimed)} reclaimed · ${formatBytes(usage.projectsBytes)} of project data retained"
                        )
                    }
                }
                LogStore.app("Temporary cache cleaned; reclaimed ${formatBytes(reclaimed)}. Project data still stored: ${formatBytes(usage.projectsBytes)}.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Storage cleanup failed") } }
                LogStore.app("Storage cleanup failed", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    /** Permanently deletes one saved workspace and removes its history entry. */
    fun deleteRecentWorkspaceStorage(path: String) {
        val current = mutableState.value
        val requested = runCatching { File(path).canonicalPath }.getOrNull() ?: return
        val isActive = current.workspace?.let { runCatching { it.canonicalPath }.getOrNull() == requested } == true
        beginOperation("Permanently deleting project data…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val reclaimed = StorageCleanup.deleteWorkspace(getApplication(), requested)
                if (isActive || SessionStore.activeWorkspace(getApplication())?.canonicalPath == requested) {
                    SessionStore.closeWorkspace(getApplication())
                }
                val remaining = SessionStore.removeRecentWorkspace(getApplication(), requested)
                val usage = StorageCleanup.inspect(getApplication())
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            workspace = if (isActive) null else workspace,
                            projectFiles = if (isActive) emptyList() else projectFiles,
                            selectedFile = if (isActive) null else selectedFile,
                            editorText = if (isActive) "" else editorText,
                            fileInfo = if (isActive) "" else fileInfo,
                            editorDirty = if (isActive) false else editorDirty,
                            recentWorkspaces = remaining,
                            recentWorkspace = remaining.firstOrNull()?.file,
                            storageUsage = usage,
                            status = "Deleted ${File(requested).name} permanently · ${formatBytes(reclaimed)} reclaimed"
                        )
                    }
                }
                LogStore.app("Permanently deleted workspace ${File(requested).name}; ${formatBytes(reclaimed)} reclaimed from app storage.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to delete project data") } }
                LogStore.app("Permanent workspace deletion failed for $requested", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    /** Deletes every saved workspace only after the user confirms the destructive Settings action. */
    fun deleteAllWorkspaceStorage() {
        beginOperation("Deleting all saved project data…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                drainDraftSave()
                val reclaimed = StorageCleanup.deleteAllWorkspaces(getApplication())
                SessionStore.clearAllWorkspaceReferences(getApplication())
                val usage = StorageCleanup.inspect(getApplication())
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            workspace = null,
                            projectFiles = emptyList(),
                            selectedFile = null,
                            editorText = "",
                            fileInfo = "",
                            editorDirty = false,
                            recentWorkspace = null,
                            recentWorkspaces = emptyList(),
                            storageUsage = usage,
                            status = "All saved projects deleted · ${formatBytes(reclaimed)} reclaimed"
                        )
                    }
                }
                LogStore.app("All saved project workspaces permanently deleted; ${formatBytes(reclaimed)} reclaimed.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to delete saved projects") } }
                LogStore.app("Deleting all workspace data failed", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    /** Deletes the APK library in files/apks without touching APKs retained in workspace baselines. */
    fun deleteImportedApkStorage() {
        beginOperation("Deleting imported APK library…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val reclaimed = StorageCleanup.deleteImportedApks(getApplication())
                val usage = StorageCleanup.inspect(getApplication())
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            importedApks = emptyList(),
                            storageUsage = usage,
                            status = "Imported APK library deleted · ${formatBytes(reclaimed)} reclaimed"
                        )
                    }
                }
                LogStore.app("Imported APK library deleted; ${formatBytes(reclaimed)} reclaimed. Project APK baselines were preserved.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to delete imported APK library") } }
                LogStore.app("Deleting imported APK library failed", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    fun closeProject() {
        val current = mutableState.value
        val root = current.workspace ?: return
        beginOperation("Saving changes and closing project…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                flushDirtyEditor(current)
                SessionStore.closeWorkspace(getApplication())
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            page = MainPage.PROJECTS, workspace = null, projectFiles = emptyList(),
                            selectedFile = null, editorText = "", fileInfo = "", editorDirty = false,
                            recentWorkspace = SessionStore.recentWorkspace(getApplication()),
                            recentWorkspaces = SessionStore.recentWorkspaces(getApplication()),
                            status = "Project closed · changes saved locally"
                        )
                    }
                }
                LogStore.app("Workspace ${root.name} closed by user; project data retained.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to close project") } }
                LogStore.app("Closing workspace failed", error)
            } finally {
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    fun openRecentWorkspace() {
        val recent = mutableState.value.recentWorkspaces.firstOrNull()
            ?: SessionStore.recentWorkspaces(getApplication()).firstOrNull()
        recent?.let { openRecentWorkspace(it.path) }
    }

    fun openRecentWorkspace(path: String) {
        val recent = SessionStore.recentWorkspaces(getApplication()).firstOrNull { it.path == path }
            ?: mutableState.value.recentWorkspaces.firstOrNull { it.path == path }
            ?: RecentWorkspaceEntry(path)
        if (!recent.isAvailable) {
            mutate { copy(error = "This recent workspace is unavailable. Remove it from the recent list or restore its folder.") }
            return
        }
        beginOperation("Opening ${recent.file.name}…")
        viewModelScope.launch {
            try {
                loadWorkspace(recent.file, recent.selectedRelativePath?.let { File(File(recent.file, "project"), it).absolutePath })
            } catch (error: Exception) {
                mutate { copy(error = error.message ?: "Unable to open recent workspace") }
            } finally {
                finishOperation()
            }
        }
    }

    fun removeRecentWorkspace(path: String) {
        val remaining = SessionStore.removeRecentWorkspace(getApplication(), path)
        mutate {
            copy(
                recentWorkspaces = remaining,
                recentWorkspace = remaining.firstOrNull()?.file,
                status = "Removed project from recent list · project files were kept"
            )
        }
        LogStore.app("Removed recent workspace entry: $path. Workspace files were not deleted.")
    }

    fun shareCurrentSource() {
        val current = mutableState.value
        val selected = current.selectedFile ?: return
        val editableExtensions = setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")
        if (selected.extension !in editableExtensions) {
            mutate { copy(error = "Select an editable source file before sharing.") }
            return
        }
        val sourceText = if (current.editorDirty) current.editorText else null
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val text = sourceText ?: selected.file.readText(Charsets.UTF_8)
                val safeName = selected.file.name.replace(Regex("[^A-Za-z0-9._-]"), "_").ifBlank { "source.gd" }
                val sharedDir = File(getApplication<Application>().cacheDir, "shared_sources").apply { mkdirs() }
                val sharedFile = File(sharedDir, safeName)
                AtomicFileWriter.writeText(sharedFile, text)
                val context = getApplication<Application>()
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", sharedFile)
                withContext(Dispatchers.Main) {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        putExtra(Intent.EXTRA_SUBJECT, selected.file.name)
                        clipData = ClipData.newUri(context.contentResolver, selected.file.name, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    context.startActivity(Intent.createChooser(send, "Share ${selected.file.name}").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
                LogStore.app("Shared current source file ${selected.relativePath}.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to share source file") } }
                LogStore.app("Sharing ${selected.relativePath} failed", error)
            }
        }
    }
    private inline fun mutate(change: OpenGDSState.() -> OpenGDSState) {
        mutableState.value = mutableState.value.change()
    }

    fun scanAll() {
        viewModelScope.launch {
            val ownsProgress = !mutableState.value.loading
            if (ownsProgress) mutate { copy(loading = true, canCancelOperation = false, status = "Scanning apps and APKs…") }
            try {
                val (apps, apks) = withContext(Dispatchers.IO) {
                    scanInstalledApps() to scanImportedApks()
                }
                mutate { copy(installedApps = apps, importedApks = apks, loading = if (ownsProgress) false else loading, canCancelOperation = if (ownsProgress) false else canCancelOperation, status = "${apps.size} apps · ${apks.size} APKs") }
                refreshStorageUsage()
                LogStore.app("Scan complete: ${apps.size} visible apps, ${apks.size} visible APK files.")
            } catch (error: Exception) {
                mutate { copy(loading = if (ownsProgress) false else loading, canCancelOperation = if (ownsProgress) false else canCancelOperation, error = error.message ?: "App scan failed", status = "Scan failed") }
                LogStore.app("Installed-app scan failed", error)
            }
        }
    }

    private fun scanInstalledApps(): List<AppRecord> {
        val pm = getApplication<Application>().packageManager
        val showSystem = SettingsStore.showSystem(getApplication())
        val includeNonGodot = SettingsStore.includeNonGodot(getApplication())
        val installed = if (Build.VERSION.SDK_INT >= 33) {
            pm.getInstalledApplications(PackageManager.ApplicationInfoFlags.of(PackageManager.GET_META_DATA.toLong()))
        } else {
            @Suppress("DEPRECATION")
            pm.getInstalledApplications(PackageManager.GET_META_DATA)
        }
        return installed.asSequence().filter { it.packageName != getApplication<Application>().packageName }
            .mapNotNull { info ->
                val system = (info.flags and (ApplicationInfo.FLAG_SYSTEM or ApplicationInfo.FLAG_UPDATED_SYSTEM_APP)) != 0
                if (system && !showSystem) return@mapNotNull null
                val paths = buildList {
                    if (info.sourceDir != null) add(info.sourceDir)
                    info.splitSourceDirs?.forEach(::add)
                }
                val godot = paths.any { ApkInspector.isGodotApk(File(it)) }
                if (!godot && !includeNonGodot) return@mapNotNull null
                val label = try { pm.getApplicationLabel(info).toString() } catch (_: Exception) { info.packageName }
                val version = try {
                    @Suppress("DEPRECATION")
                    val p = if (Build.VERSION.SDK_INT >= 33) pm.getPackageInfo(info.packageName, PackageManager.PackageInfoFlags.of(0))
                    else pm.getPackageInfo(info.packageName, 0)
                    p.versionName ?: "Unknown version"
                } catch (_: Exception) { "Unknown version" }
                AppRecord(label, info.packageName, version, system, godot, paths)
            }.sortedWith(compareByDescending<AppRecord> { it.isGodot }.thenBy { it.label.lowercase() }).toList()
    }

    private fun scanImportedApks(): List<ApkRecord> {
        val dir = File(getApplication<Application>().filesDir, "apks")
        dir.mkdirs()
        val showNonGodot = SettingsStore.includeNonGodot(getApplication())
        return dir.listFiles()?.filter { it.isFile && it.extension.equals("apk", true) }
            ?.map { ApkRecord(it.name, it.absolutePath, ApkInspector.isGodotApk(it), it.length()) }
            ?.filter { it.isGodot || showNonGodot }
            ?.sortedWith(compareByDescending<ApkRecord> { it.isGodot }.thenBy { it.name.lowercase() })
            ?: emptyList()
    }

    fun setShowSystem(value: Boolean) {
        SettingsStore.setShowSystem(getApplication(), value)
        mutate { copy(showSystemApps = value) }
        scanAll()
    }

    fun setIncludeNonGodot(value: Boolean) {
        SettingsStore.setIncludeNonGodot(getApplication(), value)
        mutate { copy(includeNonGodot = value) }
        scanAll()
    }

    fun setTheme(value: String) { SettingsStore.setTheme(getApplication(), value); mutate { copy(theme = value) } }
    fun setCompressed(value: Boolean) { SettingsStore.setCompressed(getApplication(), value); mutate { copy(compressed = value) } }
    fun setTabSize(value: Int) { SettingsStore.setTabSize(getApplication(), value); mutate { copy(tabSize = value) } }
    fun setOverwrite(value: Boolean) { SettingsStore.setOverwrite(getApplication(), value); mutate { copy(overwrite = value) } }
    fun setContinueOnError(value: Boolean) { SettingsStore.setContinueOnError(getApplication(), value); mutate { copy(continueOnError = value) } }
    fun setAlwaysUnsignedOutput(value: Boolean) {
        SettingsStore.setAlwaysUnsignedOutput(getApplication(), value)
        mutate { copy(alwaysUnsignedOutput = value) }
    }

    fun setAutoCleanupAfterRepack(value: Boolean) {
        SettingsStore.setAutoCleanupAfterRepack(getApplication(), value)
        mutate { copy(autoCleanupAfterRepack = value) }
    }

    fun setDefaultOutputDirectory(uri: Uri) {
        try {
            getApplication<Application>().contentResolver.takePersistableUriPermission(
                uri,
                android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION or android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
        } catch (_: Exception) { /* Some document providers grant a durable tree permission directly. */ }
        getApplication<Application>().getSharedPreferences("opengds.settings", 0).edit().putString("apk_output_tree_uri", uri.toString()).commit()
        mutate { copy(outputDirectoryConfigured = true, status = "Default APK output folder saved") }
        LogStore.app("Default APK output folder updated.")
    }

    fun importApk(uri: Uri) {
        viewModelScope.launch {
            beginOperation("Importing APK…")
            try {
                val name = FileIntake.displayName(getApplication(), uri)
                if (!name.endsWith(".apk", true)) throw IllegalArgumentException("Select an .apk file")
                val dest = File(getApplication<Application>().filesDir, "apks/${System.currentTimeMillis()}_${name.replace(Regex("[^A-Za-z0-9._-]"), "_")}")
                FileIntake.copyUri(getApplication(), uri, dest, cancelFile = cancelFile)
                val godot = withContext(Dispatchers.IO) { ApkInspector.isGodotApk(dest) }
                LogStore.app("Imported ${dest.name} (${if (godot) "Godot" else "non-Godot"}, ${formatBytes(dest.length())}).")
                scanAll()
                mutate { copy(status = if (godot) "Godot APK imported" else "APK imported; enable non-Godot visibility to inspect it") }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "APK import failed", status = if (cancelled) "Import cancelled" else "Import failed") }
                LogStore.app(if (cancelled) "APK import cancelled." else "APK import failed", error)
            } finally { finishOperation() }
        }
    }

    fun openInstalledApp(record: AppRecord) {
        viewModelScope.launch {
            var pendingWorkspace: File? = null
            beginOperation("Extracting ${record.label}…")
            try {
                val root = withContext(Dispatchers.IO) {
                    val workspace = ProjectWorkspace.create(getApplication(), record.label)
                    pendingWorkspace = workspace
                    val count = ProjectWorkspace.importInstalledApp(record, workspace, cancelFile)
                    LogStore.app("Extracted $count APK archive entries from ${record.packageName}.")
                    GodotPckExtractor.extractPacks(File(workspace, "project"), cancelFile).forEach { LogStore.app(it.message) }
                    workspace
                }
                loadWorkspace(root)
                pendingWorkspace = null
            } catch (error: Exception) {
                withContext(Dispatchers.IO) { pendingWorkspace?.deleteRecursively() }
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "Unable to open app", status = if (cancelled) "Opening cancelled" else "Open failed") }
                LogStore.app("Opening installed package ${record.packageName} ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { finishOperation() }
        }
    }

    fun openApk(record: ApkRecord) {
        viewModelScope.launch {
            var pendingWorkspace: File? = null
            beginOperation("Extracting ${record.name}…")
            try {
                val root = withContext(Dispatchers.IO) {
                    val workspace = ProjectWorkspace.create(getApplication(), File(record.name).nameWithoutExtension)
                    pendingWorkspace = workspace
                    val sourceApk = File(record.path)
                    val count = ProjectWorkspace.importApk(sourceApk, workspace, cancelFile = cancelFile)
                    val sourceDir = File(workspace, "source").apply { mkdirs() }
                    FileIntake.copyFile(sourceApk, File(sourceDir, "base.apk"), cancelFile)
                    File(sourceDir, "base.name").writeText(record.name.replace(Regex("^\\d+_"), ""), Charsets.UTF_8)
                    LogStore.app("Extracted $count APK archive entries from ${record.name}; original APK retained as repack baseline.")
                    GodotPckExtractor.extractPacks(File(workspace, "project"), cancelFile).forEach { LogStore.app(it.message) }
                    workspace
                }
                loadWorkspace(root)
                pendingWorkspace = null
            } catch (error: Exception) {
                withContext(Dispatchers.IO) { pendingWorkspace?.deleteRecursively() }
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "Unable to open APK", status = if (cancelled) "Opening cancelled" else "Open failed") }
                LogStore.app("Opening APK ${record.name} ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { finishOperation() }
        }
    }

    fun scanApkFolder(uri: Uri) {
        viewModelScope.launch {
            beginOperation("Scanning selected folder for APK files…")
            try {
                val count = withContext(Dispatchers.IO) {
                    val tree = DocumentFile.fromTreeUri(getApplication(), uri) ?: error("Unable to access selected folder")
                    val destination = File(getApplication<Application>().filesDir, "apks").apply { mkdirs() }
                    var copied = 0
                    var bytes = 0L
                    fun visit(folder: DocumentFile, depth: Int) {
                        if (cancelFile.exists()) throw IllegalStateException("Operation cancelled by user")
                        if (depth > 24 || copied >= 500 || bytes >= 2L * 1024 * 1024 * 1024) return
                        folder.listFiles().forEach { child ->
                            if (cancelFile.exists()) throw IllegalStateException("Operation cancelled by user")
                            if (copied >= 500 || bytes >= 2L * 1024 * 1024 * 1024) return
                            if (child.isDirectory) visit(child, depth + 1)
                            else if (child.isFile && child.name?.endsWith(".apk", true) == true) {
                                val originalName = child.name ?: "imported.apk"
                                val safe = originalName.replace(Regex("[^A-Za-z0-9._-]"), "_")
                                val output = File(destination, "${System.currentTimeMillis()}_${copied}_${safe}")
                                val temporary = File(destination, output.name + ".copying")
                                try {
                                    getApplication<Application>().contentResolver.openInputStream(child.uri)?.use { input ->
                                        FileOutputStream(temporary).use { out ->
                                            val buffer = ByteArray(64 * 1024)
                                            var fileBytes = 0L
                                            while (true) {
                                                if (cancelFile.exists()) throw IllegalStateException("Operation cancelled by user")
                                                val read = input.read(buffer)
                                                if (read < 0) break
                                                fileBytes += read
                                                bytes += read
                                                if (fileBytes > 512L * 1024 * 1024 || bytes > 2L * 1024 * 1024 * 1024) {
                                                    throw IllegalStateException("APK folder scan reached its safety limit")
                                                }
                                                out.write(buffer, 0, read)
                                            }
                                            out.fd.sync()
                                        }
                                    } ?: throw IllegalStateException("Unable to read ${child.name}")
                                    if (!temporary.renameTo(output)) throw IllegalStateException("Unable to store ${child.name}")
                                    copied++
                                } catch (error: Exception) {
                                    temporary.delete()
                                    output.delete()
                                    throw error
                                }
                            }
                        }
                    }
                    visit(tree, 0)
                    copied
                }
                LogStore.app("Imported $count APK file(s) from selected folder.")
                scanAll()
                mutate { copy(status = "Found and imported $count APK file(s)") }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "APK folder scan failed", status = if (cancelled) "APK folder scan cancelled" else "Folder scan failed") }
                LogStore.app("APK folder scan ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { finishOperation() }
        }
    }

    fun importFolder(uri: Uri) {
        viewModelScope.launch {
            var pendingWorkspace: File? = null
            beginOperation("Importing project folder…")
            try {
                val root = withContext(Dispatchers.IO) {
                    val document = DocumentFile.fromTreeUri(getApplication(), uri) ?: error("Unable to access the selected folder")
                    val workspace = ProjectWorkspace.create(getApplication(), document.name ?: "GodotProject")
                    pendingWorkspace = workspace
                    val projectDir = File(workspace, "project")
                    copyDocumentTree(document, projectDir, cancelFile = cancelFile)
                    GodotPckExtractor.extractPacks(projectDir, cancelFile).forEach { LogStore.app(it.message) }
                    workspace
                }
                loadWorkspace(root)
                pendingWorkspace = null
            } catch (error: Exception) {
                withContext(Dispatchers.IO) { pendingWorkspace?.deleteRecursively() }
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "Folder import failed", status = if (cancelled) "Folder import cancelled" else "Import failed") }
                LogStore.app("Folder import ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { finishOperation() }
        }
    }

    private data class FolderImportLimits(var files: Int = 0, var totalBytes: Long = 0)

    private fun copyDocumentTree(
        source: DocumentFile,
        destination: File,
        depth: Int = 0,
        limits: FolderImportLimits = FolderImportLimits(),
        cancelFile: File? = null
    ) {
        if (depth > 32) throw IllegalStateException("Project folder nesting exceeds 32 levels")
        destination.mkdirs()
        source.listFiles().forEach { child ->
            if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
            val name = child.name ?: return@forEach
            if (name == "." || name == ".." || name.contains('/') || name.contains('\\')) return@forEach
            val output = File(destination, name)
            if (child.isDirectory) {
                copyDocumentTree(child, output, depth + 1, limits, cancelFile)
            } else if (child.isFile) {
                limits.files++
                if (limits.files > 20_000) throw IllegalStateException("Project contains more than 20,000 files")
                val temporary = File(output.parentFile, output.name + ".copying")
                try {
                    getApplication<Application>().contentResolver.openInputStream(child.uri)?.use { input ->
                        FileOutputStream(temporary).use { out ->
                            val buffer = ByteArray(128 * 1024)
                            var fileBytes = 0L
                            while (true) {
                                if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
                                val count = input.read(buffer)
                                if (count < 0) break
                                fileBytes += count
                                limits.totalBytes += count
                                if (fileBytes > 512L * 1024 * 1024 || limits.totalBytes > 2L * 1024 * 1024 * 1024) {
                                    throw IllegalStateException("Project folder import reached the 512 MiB/file or 2 GiB/total safety limit")
                                }
                                out.write(buffer, 0, count)
                            }
                        }
                    } ?: throw IllegalStateException("Unable to read ${child.name}")
                    if (!temporary.renameTo(output)) throw IllegalStateException("Unable to copy ${child.name}")
                } catch (error: Exception) {
                    temporary.delete()
                    throw error
                }
            }
        }
    }

    /** Import one or more standalone GDScript/GDSC files, creating a workspace when needed. */
    fun importSources(uris: List<Uri>) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            val existingWorkspace = mutableState.value.workspace
            var createdWorkspace: File? = null
            beginOperation("Importing GDScript files…")
            try {
                val (workspace, imported) = withContext(Dispatchers.IO) {
                    val root = existingWorkspace ?: ProjectWorkspace.create(getApplication(), "StandaloneScripts")
                    if (existingWorkspace == null) createdWorkspace = root
                    val projectDir = File(root, "project").canonicalFile.apply { mkdirs() }
                    val files = uris.map { uri -> importScriptDocument(uri, projectDir) }
                    root to files
                }
                val first = imported.firstOrNull()
                loadWorkspace(workspace, first?.absolutePath)
                mutate { copy(status = "Imported ${imported.size} file(s) · ready to edit or compile") }
                imported.forEach { LogStore.app("Imported ${it.name} into ${workspace.name}.") }
            } catch (error: Exception) {
                createdWorkspace?.deleteRecursively()
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "File import failed", status = if (cancelled) "File import cancelled" else "Import failed") }
                if (existingWorkspace != null) refreshFiles()
                LogStore.app("GDScript file import ${if (cancelFile.exists()) "cancelled" else "failed"}", error)
            } finally { finishOperation() }
        }
    }

    /** Backwards-compatible single-file entry point. */
    fun importSource(uri: Uri) = importSources(listOf(uri))

    private suspend fun importScriptDocument(uri: Uri, projectDir: File): File {
        val originalName = FileIntake.displayName(getApplication(), uri)
            .substringAfterLast('/').substringAfterLast('\\')
        val extension = originalName.substringAfterLast('.', "").lowercase()
        if (extension !in setOf("gd", "gdc")) {
            throw IllegalArgumentException("Select only .gd or .gdc files. For a complete project, import its folder instead.")
        }
        val safeName = originalName
            .replace(Regex("[^A-Za-z0-9._ -]"), "_")
            .trim().take(180)
        if (safeName.isBlank() || safeName == "." || safeName == "..") {
            throw IllegalArgumentException("The selected file has an invalid name")
        }
        val target = File(projectDir, safeName).canonicalFile
        if (target.parentFile != projectDir) throw IllegalArgumentException("Invalid file name")

        val temporary = File(projectDir, "${safeName}.importing")
        val backup = File(projectDir, "${safeName}.bak")
        FileIntake.copyUri(getApplication(), uri, temporary, maxBytes = 512L * 1024 * 1024, cancelFile = cancelFile)

        if (target.exists()) {
            if (!SettingsStore.overwrite(getApplication())) {
                temporary.delete()
                throw IllegalStateException("${target.name} already exists. Enable 'Replace existing .gd/.gdc outputs' in Settings to replace it.")
            }
            backup.delete()
            if (!target.renameTo(backup)) {
                temporary.delete()
                throw IllegalStateException("Unable to back up ${target.name} before replacement")
            }
        }
        if (!temporary.renameTo(target)) {
            if (backup.exists()) backup.renameTo(target)
            temporary.delete()
            throw IllegalStateException("Unable to import ${target.name}; the previous file was restored")
        }
        if (target.extension.equals("gdc", true)) {
            val validation = withContext(Dispatchers.IO) { backend.validateGdc(target.absolutePath) }
            if (!validation.optBoolean("valid")) {
                LogStore.app("Imported ${target.name}, but it is not a supported GDSC v101 file.")
            }
        }
        return target
    }

    /** Import an APK directly into an editable workspace from the Editor's add menu. */
    fun importAndOpenApk(uri: Uri) {
        viewModelScope.launch {
            var transientSourceApk: File? = null
            beginOperation("Importing and opening APK…")
            try {
                val originalName = FileIntake.displayName(getApplication(), uri)
                if (!originalName.endsWith(".apk", true)) throw IllegalArgumentException("Select an .apk file")
                val safeName = originalName.replace(Regex("[^A-Za-z0-9._-]"), "_")
                val sourceApk = File(getApplication<Application>().cacheDir, "editor-apk-imports/${System.currentTimeMillis()}_$safeName")
                sourceApk.parentFile?.mkdirs()
                transientSourceApk = sourceApk
                FileIntake.copyUri(getApplication(), uri, sourceApk, cancelFile = cancelFile)
                val workspace = withContext(Dispatchers.IO) {
                    val root = ProjectWorkspace.create(getApplication(), sourceApk.nameWithoutExtension)
                    try {
                        val count = ProjectWorkspace.importApk(sourceApk, root, cancelFile = cancelFile)
                        val sourceDir = File(root, "source").apply { mkdirs() }
                        FileIntake.copyFile(sourceApk, File(sourceDir, "base.apk"), cancelFile)
                        File(sourceDir, "base.name").writeText(originalName, Charsets.UTF_8)
                        LogStore.app("Extracted $count APK archive entries; original APK retained for repacking.")
                        GodotPckExtractor.extractPacks(File(root, "project"), cancelFile).forEach { LogStore.app(it.message) }
                        root
                    } catch (error: Exception) {
                        root.deleteRecursively()
                        throw error
                    }
                }
                scanAll()
                loadWorkspace(workspace)
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "APK import failed", status = if (cancelled) "APK import cancelled" else "Import failed") }
                LogStore.app("Importing APK from the Editor ${if (cancelled) "cancelled" else "failed"}", error)
            } finally {
                transientSourceApk?.delete()
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    /** Create an editable GDScript file without requiring an APK or an imported project. */
    fun createNewScript() {
        viewModelScope.launch {
            val currentWorkspace = mutableState.value.workspace
            mutate { copy(loading = true, status = "Creating GDScript…", error = null) }
            try {
                val (workspace, script) = withContext(Dispatchers.IO) {
                    val root = currentWorkspace ?: ProjectWorkspace.create(getApplication(), "StandaloneScripts")
                    val projectDir = File(root, "project").apply { mkdirs() }
                    var index = 1
                    var candidate = File(projectDir, "NewScript.gd")
                    while (candidate.exists()) {
                        index++
                        candidate = File(projectDir, "NewScript_$index.gd")
                    }
                    candidate.writeText("extends Node\n\nfunc _ready():\n\tpass\n", Charsets.UTF_8)
                    root to candidate
                }
                loadWorkspace(workspace, script.absolutePath)
                mutate { copy(status = "Created ${script.name} · edit and compile to GDSC v101") }
                LogStore.app("Created ${script.relativeTo(File(workspace, "project"))} in ${workspace.name}.")
            } catch (error: Exception) {
                mutate { copy(loading = false, error = error.message ?: "Unable to create GDScript") }
                LogStore.app("Creating a new GDScript failed", error)
            }
        }
    }

    fun replaceSelectedFile(uri: Uri) {
        val current = mutableState.value
        val selected = current.selectedFile ?: return
        val workspace = current.workspace ?: return
        if (current.editorDirty) {
            mutate { copy(error = "Save or discard the current editor changes before replacing this file.") }
            return
        }
        val projectRoot = File(workspace, "project").canonicalFile
        val target = selected.file.canonicalFile
        if (!target.toPath().startsWith(projectRoot.toPath()) || !target.isFile) return

        beginOperation("Replacing ${selected.file.name}…")
        viewModelScope.launch {
            try {
                val replacementName = FileIntake.displayName(getApplication(), uri)
                if (!replacementName.substringAfterLast('.', "").equals(selected.extension, true)) {
                    throw IllegalArgumentException("Choose a .${selected.extension} file to replace ${selected.file.name}.")
                }
                val temp = File(target.parentFile, target.name + ".replacement")
                val backup = File(target.parentFile, target.name + ".bak")
                FileIntake.copyUri(getApplication(), uri, temp, maxBytes = 512L * 1024 * 1024, cancelFile = cancelFile)
                if (selected.extension == "gdc") {
                    val validation = withContext(Dispatchers.IO) { backend.validateGdc(temp.absolutePath) }
                    if (!validation.optBoolean("valid")) {
                        temp.delete()
                        throw IllegalArgumentException("Replacement rejected: only a valid GDSC v101 file can replace this GDC.")
                    }
                }
                backup.delete()
                if (!target.renameTo(backup)) {
                    temp.delete()
                    throw IllegalStateException("Unable to create a backup of ${target.name}")
                }
                if (!temp.renameTo(target)) {
                    backup.renameTo(target)
                    temp.delete()
                    throw IllegalStateException("Unable to replace ${target.name}; the original file was restored")
                }
                if (selected.extension == "pck") {
                    GodotPckExtractor.extractPacks(projectRoot, cancelFile).forEach { LogStore.app(it.message) }
                }
                LogStore.app("Replaced ${selected.relativePath}; previous file saved as ${backup.name}.")
                withContext(Dispatchers.Main) {
                    mutate { copy(status = "Replaced ${target.name} · backup retained") }
                    refreshFiles(target.absolutePath)
                }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                mutate { copy(error = if (cancelled) null else error.message ?: "File replacement failed", status = if (cancelled) "Replacement cancelled" else status) }
                LogStore.app("Replacement ${if (cancelled) "cancelled" else "failed"} for ${selected.relativePath}", error)
            } finally { finishOperation() }
        }
    }

    private suspend fun loadWorkspace(root: File, selectPath: String? = null) {
        val files = withContext(Dispatchers.IO) { ProjectWorkspace.listFiles(root, backend) }
        val gdcCount = files.count { it.extension == "gdc" && it.validGdc }
        val selected = selectPath?.let { path -> files.firstOrNull { it.file.absolutePath == path } }
        withContext(Dispatchers.IO) { SessionStore.saveWorkspace(getApplication(), root, selected?.relativePath) }
        mutate {
            copy(
                workspace = root, recentWorkspace = root, recentWorkspaces = SessionStore.recentWorkspaces(getApplication()), projectFiles = files, selectedFile = selected,
                editorText = "", fileInfo = "", editorDirty = false, loading = false, canCancelOperation = false,
                page = MainPage.EDITOR,
                status = "${files.size} project files · $gdcCount validated GDSC v101 files"
            )
        }
        selected?.let(::openProjectFile)
        refreshStorageUsage()
        LogStore.app("Workspace opened: ${root.name}; ${files.size} supported files visible.")
    }

    fun refreshFiles(selectPath: String? = null) {
        val root = mutableState.value.workspace ?: return
        viewModelScope.launch {
            val files = withContext(Dispatchers.IO) { ProjectWorkspace.listFiles(root, backend) }
            val selected = selectPath?.let { path -> files.firstOrNull { it.file.absolutePath == path } }
            mutate { copy(projectFiles = files, selectedFile = selected ?: selectedFile?.let { old -> files.firstOrNull { it.file == old.file } }) }
            if (selected != null) openProjectFile(selected)
            refreshStorageUsage()
        }
    }

    fun openProjectFile(file: ProjectFile, jumpToLine: Int? = null) {
        val previous = mutableState.value
        val workspace = previous.workspace
        val pendingDraftSave = draftSaveJob
        draftSaveJob = null
        pendingDraftSave?.cancel()
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // Finish any already-running journal write before flushing the previous file.
                pendingDraftSave?.join()
                if (workspace != null) {
                    val oldFile = previous.selectedFile
                    if (previous.editorDirty && oldFile != null && oldFile.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")) {
                        AtomicFileWriter.writeText(oldFile.file, previous.editorText, keepBackup = true)
                        SessionStore.clearDraft(getApplication())
                    }
                    // Persist the new selection only after the previous dirty buffer is durable.
                    SessionStore.saveSelection(getApplication(), workspace, file.relativePath)
                }
                if (file.extension == "gdc") {
                    if (!file.validGdc) {
                        withContext(Dispatchers.Main) {
                            mutate {
                                copy(
                                    selectedFile = file,
                                    editorText = "",
                                    fileInfo = "This file is not a validated GDSC v101 bytecode file. It remains available for inspection and export, but OpenGDS can only decompile supported v101 files.\n\nFile: ${file.relativePath}\nSize: ${formatBytes(file.bytes)}",
                                    editorDirty = false,
                                    status = "Unsupported or invalid GDSC file"
                                )
                            }
                        }
                        return@launch
                    }
                    val info = backend.info(file.file.absolutePath)
                    withContext(Dispatchers.Main) {
                        mutate { copy(selectedFile = file, editorText = "", fileInfo = info, editorDirty = false, status = "GDSC v101 · decompile before editing") }
                    }
                    return@launch
                }
                if (file.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")) {
                    if (file.bytes > MAX_TEXT_FILE) throw IllegalStateException("File is larger than the 8 MiB editor limit")
                    val content = file.file.readText(Charsets.UTF_8)
                    val draft = workspace?.let { SessionStore.readDraft(getApplication(), it, file.relativePath) }
                    val restoredText = draft ?: content
                    withContext(Dispatchers.Main) {
                        mutate {
                            copy(
                                selectedFile = file, editorText = restoredText, fileInfo = "",
                                editorDirty = draft != null,
                                status = if (draft != null) "Restored unsaved draft · ${file.relativePath}" else "${file.relativePath} · ${formatBytes(file.bytes)}",
                                editorJumpToLine = jumpToLine?.coerceAtLeast(1) ?: 0,
                                editorJumpRequestId = if (jumpToLine != null) editorJumpRequestId + 1 else editorJumpRequestId
                            )
                        }
                    }
                } else {
                    withContext(Dispatchers.Main) {
                        mutate { copy(selectedFile = file, editorText = "", fileInfo = "Binary or unsupported preview\n\nFile: ${file.relativePath}\nSize: ${formatBytes(file.bytes)}\n\nOpenGDS edits GDScript and imported Smali text files. GDSC files must be decompiled first.", editorDirty = false, status = "Binary file selected") }
                    }
                }
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Unable to read file") } }
                LogStore.app("Opening ${file.relativePath} failed", error)
            }
        }
    }

    fun updateEditor(text: String) {
        val current = mutableState.value
        mutate { copy(editorText = text, editorDirty = true) }
        val workspace = current.workspace ?: return
        val selected = current.selectedFile ?: return
        if (selected.extension !in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")) return
        draftSaveJob?.cancel()
        draftSaveJob = viewModelScope.launch(Dispatchers.IO) {
            delay(100)
            runCatching { SessionStore.saveDraft(getApplication(), workspace, selected.relativePath, text) }
                .onFailure { LogStore.app("Could not persist editor recovery draft", it) }
        }
    }

    fun saveEditor() {
        val current = mutableState.value
        val file = current.selectedFile ?: return
        if (file.extension !in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                drainDraftSave()
                AtomicFileWriter.writeText(file.file, current.editorText, keepBackup = true)
                current.workspace?.let { SessionStore.clearDraft(getApplication()) }
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            editorDirty = if (selectedFile?.file == file.file) editorText != current.editorText else editorDirty,
                            status = "Saved ${file.relativePath}"
                        )
                    }
                }
                LogStore.app("Saved ${file.relativePath}.")
                refreshFiles()
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Save failed") } }
                LogStore.app("Saving ${file.relativePath} failed", error)
            }
        }
    }

    fun decompileSelected() {
        val current = mutableState.value
        val file = current.selectedFile ?: return
        val workspace = current.workspace ?: return
        if (file.extension != "gdc" || !file.validGdc) return
        beginOperation("Decompiling ${file.file.name}…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val target = file.file.resolveSibling(file.file.nameWithoutExtension + ".gd")
                if (target.exists() && !SettingsStore.overwrite(getApplication())) {
                    throw IllegalStateException("${target.name} already exists. Enable 'Replace existing .gd/.gdc outputs' in Settings to replace it.")
                }
                val source = backend.decompile(file.file.absolutePath)
                AtomicFileWriter.writeText(target, source, keepBackup = true)
                val relativePath = file.relativePath.substringBeforeLast('.', file.relativePath) + ".gd"
                val generated = ProjectFile(target, relativePath, "gd", target.length(), false)
                SessionStore.saveSelection(getApplication(), workspace, relativePath)
                val updatedFiles = (current.projectFiles.filterNot { it.file.canonicalPath == target.canonicalPath } + generated)
                    .sortedWith(compareBy<ProjectFile>({ it.relativePath.count { char -> char == '/' } }, { it.relativePath.lowercase() }))
                withContext(Dispatchers.Main) {
                    // Publish the generated editor buffer and selection together. This avoids the old
                    // refreshFiles/openProjectFile race that left the mobile UI on the Files pane.
                    mutate {
                        copy(
                            projectFiles = updatedFiles,
                            selectedFile = generated,
                            editorText = source,
                            fileInfo = "",
                            editorDirty = false,
                            status = "Decompiled · ${target.name} · ready to edit"
                        )
                    }
                }
                LogStore.core("Decompiled ${file.relativePath} -> ${target.name}; editor buffer loaded immediately.")
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "Decompilation failed", status = if (cancelled) "Decompilation cancelled" else status) } }
                LogStore.core("Decompilation ${if (cancelled) "cancelled" else "failed"} for ${file.relativePath}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun compileSelected() {
        val current = mutableState.value
        val file = current.selectedFile ?: return
        if (file.extension != "gd") return
        beginOperation("Compiling ${file.file.name}…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                drainDraftSave()
                // Compile the exact editor buffer and persist it as the .gd source as well.
                if (current.editorDirty) {
                    AtomicFileWriter.writeText(file.file, current.editorText, keepBackup = true)
                    current.workspace?.let { SessionStore.clearDraft(getApplication()) }
                    withContext(Dispatchers.Main) { mutate { copy(editorDirty = false, status = "Saved source · compiling ${file.file.name}…") } }
                }
                val target = file.file.resolveSibling(file.file.nameWithoutExtension + ".gdc")
                val overwrite = SettingsStore.overwrite(getApplication())
                if (target.exists() && !overwrite) throw IllegalStateException("${target.name} already exists. enable 'Replace existing .gd/.gdc outputs' in Settings to replace it.")
                if (target.exists()) File(target.absolutePath + ".bak").writeBytes(target.readBytes())
                val result = backend.compile(current.editorText, target.absolutePath,
                    SettingsStore.compressed(getApplication()), SettingsStore.tabSize(getApplication()), overwrite)
                LogStore.core("Compiled ${file.relativePath} -> ${target.name}; ${result.optInt("tokens")} tokens; ${result.optString("sha256")}.")
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            editorDirty = if (selectedFile?.file == file.file) editorText != current.editorText else editorDirty,
                            status = "Compiled ${target.name} · ${formatBytes(result.optLong("bytes"))}"
                        )
                    }
                    refreshFiles()
                }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "Compilation failed", status = if (cancelled) "Compilation cancelled" else status) } }
                LogStore.core("Compilation ${if (cancelled) "cancelled" else "failed"} for ${file.relativePath}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun rebuildPck() {
        val current = mutableState.value
        val workspace = current.workspace ?: return
        val selected = current.selectedFile ?: return
        val projectRoot = File(workspace, "project")
        if (!GodotPckExtractor.canRebuild(projectRoot, selected.file)) return
        beginOperation("Rebuilding embedded PCK…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                drainDraftSave()
                if (current.editorDirty && selected.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")) {
                    AtomicFileWriter.writeText(selected.file, current.editorText, keepBackup = true)
                    SessionStore.clearDraft(getApplication())
                    withContext(Dispatchers.Main) {
                        mutate { copy(editorDirty = if (selectedFile?.file == selected.file) editorText != current.editorText else editorDirty) }
                    }
                }
                val message = GodotPckExtractor.rebuildForFile(projectRoot, selected.file, cancelFile)
                LogStore.app(message)
                withContext(Dispatchers.Main) {
                    mutate { copy(editorDirty = false, status = "PCK rebuilt · original backup retained") }
                    refreshFiles(selected.file.absolutePath)
                }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "PCK rebuild failed", status = if (cancelled) "PCK rebuild cancelled" else status) } }
                LogStore.app("PCK rebuild ${if (cancelled) "cancelled" else "failed"} for ${selected.relativePath}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    /** Build edited GDScript, rebuild embedded PCKs, sign and export installable APK file(s). */
    fun repackApk(
        signingMode: String = "local",
        keystoreUri: Uri? = null,
        keystorePassword: String? = null,
        keystoreAlias: String? = null,
        keyPassword: String? = null
    ) {
        val current = mutableState.value
        val workspace = current.workspace ?: return
        val outputUri = SettingsStore.outputTreeUri(getApplication())?.let { Uri.parse(it) }
        if (outputUri == null) {
            mutate { copy(error = "Choose a default APK output folder in Settings first.") }
            return
        }
        if (!File(workspace, "source/base.apk").isFile) {
            mutate { copy(error = "This workspace has no original APK. Open an APK or installed app, not a folder-only project.") }
            return
        }
        beginOperation("Preparing installable APK export…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                flushDirtyEditor(current)
                if (current.editorDirty) withContext(Dispatchers.Main) {
                    mutate { copy(editorDirty = if (selectedFile?.file == current.selectedFile?.file) editorText != current.editorText else editorDirty) }
                }
                val projectRoot = File(workspace, "project")
                val gdCount = projectRoot.walkTopDown().count { it.isFile && it.extension.equals("gd", true) }
                if (gdCount > 0) {
                    withContext(Dispatchers.Main) { mutate { copy(loading = true, status = "Compiling $gdCount GDScript file(s)…", error = null) } }
                    val compiled = backend.compileAll(
                        projectRoot.absolutePath,
                        SettingsStore.compressed(getApplication()),
                        SettingsStore.tabSize(getApplication()),
                        true,
                        false
                    )
                    val messages = compiled.optJSONArray("messages")
                    if (messages != null) for (i in 0 until messages.length()) LogStore.core(messages.optString(i))
                    if (compiled.optInt("failed") > 0) {
                        throw IllegalStateException("GDScript compilation failed (${compiled.optInt("failed")} file(s)); APK was not repacked. See Logs.")
                    }
                    LogStore.core("Repack pipeline compiled ${compiled.optInt("ok")} GDScript file(s).")
                }

                val smaliSourceCount = projectRoot.walkTopDown().count {
                    it.isDirectory && it.parentFile?.name == "smali" && it.name.matches(Regex("classes(?:[2-9]|[1-9][0-9]+)?"))
                }
                if (smaliSourceCount > 0) {
                    withContext(Dispatchers.Main) { mutate { copy(status = "Assembling $smaliSourceCount Smali source tree(s)…") } }
                    SmaliToolchain.assemble(projectRoot, overwrite = true).forEach { LogStore.core(it) }
                }

                withContext(Dispatchers.Main) { mutate { copy(status = "Rebuilding embedded Godot PCK archives…") } }
                val rebuiltPcks = GodotPckExtractor.rebuildAll(projectRoot, cancelFile)
                rebuiltPcks.forEach { LogStore.app(it) }
                if (rebuiltPcks.isEmpty()) {
                    LogStore.app("No standalone PCK archive was found. Loose .gdc entries are preserved/replaced directly in their APK ZIP location.")
                }

                withContext(Dispatchers.Main) { mutate { copy(status = "Repacking APK archive(s)…") } }
                val alwaysUnsigned = signingMode == "unsigned"
                val outputs = ApkRepacker.rebuild(
                    getApplication(), workspace, outputUri, cancelFile,
                    alwaysUnsigned = alwaysUnsigned,
                    signingMode = signingMode,
                    keystoreUri = keystoreUri,
                    keystorePassword = keystorePassword,
                    keystoreAlias = keystoreAlias,
                    keyPassword = keyPassword
                )
                if (outputs.isEmpty()) throw IllegalStateException("No original APK was found. Reopen the APK or installed app to create a repackable workspace.")
                val unsignedOutputs = outputs.filter {
                    it.endsWith("_unsigned.apk", ignoreCase = true) ||
                        it.endsWith("_unsigned.apks", ignoreCase = true) ||
                        it.endsWith("_unsigned.xapk", ignoreCase = true)
                }
                val unsignedCount = unsignedOutputs.size
                val splitSet = outputs.any { it.endsWith(".apks", ignoreCase = true) || it.endsWith(".xapk", ignoreCase = true) }
                val signedCount = outputs.size - unsignedCount
                outputs.forEach { name ->
                    when {
                        name.endsWith("_unsigned.apk", ignoreCase = true) || name.endsWith("_unsigned.apks", ignoreCase = true) || name.endsWith("_unsigned.xapk", ignoreCase = true) ->
                            LogStore.app(
                                if (alwaysUnsigned) "Created unsigned APK output as requested in Settings: $name · sign before installation."
                                else "Created unsigned APK output: $name · unsigned export was explicitly selected."
                            )
                        name.endsWith(".xapk", ignoreCase = true) ->
                            LogStore.app("Created signed XAPK v2 bundle: $name · use an XAPK-compatible installer to install every split in one session.")
                        name.endsWith(".apks", ignoreCase = true) ->
                            LogStore.app("Created signed APK collection: $name · extract and install base plus every split together.")
                        else -> LogStore.app("Created signed installable APK: $name")
                    }
                }

                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            editorDirty = if (selectedFile?.file == current.selectedFile?.file) editorText != current.editorText else editorDirty,
                            status = when {
                                splitSet && unsignedCount > 0 -> "Unsigned XAPK exported · sign every inner APK with one certificate before installation"
                                splitSet -> "XAPK exported · install with an XAPK-compatible installer"
                                unsignedCount > 0 -> "Unsigned APK exported · sign it before installation"
                                else -> "APK export complete · $signedCount signed APK · workspace kept open"
                            }
                        )
                    }
                    refreshFiles()
                    refreshStorageUsage()
                }
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "APK export failed", status = if (cancelled) "APK export cancelled" else "APK export failed") } }
                LogStore.app("APK export ${if (cancelled) "cancelled" else "failed"}; original APK baseline retained", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun runReport(mode: String) {
        val file = mutableState.value.selectedFile ?: return
        if (file.extension != "gdc" || !file.validGdc) return
        beginOperation("Generating ${mode.uppercase()} report…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val result = backend.report(mode, file.file.absolutePath)
                withContext(Dispatchers.Main) { mutate { copy(fileInfo = result, status = "${mode.uppercase()} report ready") } }
                LogStore.core("${mode.uppercase()} report generated for ${file.relativePath}.")
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "Report failed", status = if (cancelled) "Report cancelled" else status) } }
                LogStore.core("${mode.uppercase()} report ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun decompileAll() {
        val root = mutableState.value.workspace ?: return
        beginOperation("Decompiling project GDC files…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val force = SettingsStore.overwrite(getApplication())
                val result = backend.decompileAll(File(root, "project").absolutePath, force, SettingsStore.continueOnError(getApplication()))
                val messages = result.optJSONArray("messages")
                if (messages != null) for (i in 0 until messages.length()) LogStore.core(messages.optString(i))
                val ok = result.optInt("ok")
                val failed = result.optInt("failed")
                val skipped = result.optInt("skipped")
                withContext(Dispatchers.Main) {
                    mutate { copy(status = "Batch decompile: $ok done · $failed failed · $skipped skipped") }
                    refreshFiles()
                }
                LogStore.core("Batch decompile finished: $ok completed, $failed failed, $skipped unsupported/non-v101 files skipped.")
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "Batch decompilation failed", status = if (cancelled) "Batch decompilation cancelled" else status) } }
                LogStore.core("Batch decompilation ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    private suspend fun drainDraftSave() {
        val pending = draftSaveJob
        draftSaveJob = null
        pending?.cancel()
        pending?.join()
    }

    private suspend fun flushDirtyEditor(current: OpenGDSState) {
        drainDraftSave()
        val selected = current.selectedFile ?: return
        val editable = selected.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")
        if (current.editorDirty && editable) {
            AtomicFileWriter.writeText(selected.file, current.editorText, keepBackup = true)
            SessionStore.clearDraft(getApplication())
        }
    }

    fun compileAll() {
        val root = mutableState.value.workspace ?: return
        val current = mutableState.value
        beginOperation("Compiling project GDScript files…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                flushDirtyEditor(current)
                if (current.editorDirty) {
                    withContext(Dispatchers.Main) {
                        mutate {
                            copy(
                                editorDirty = if (selectedFile?.file == current.selectedFile?.file) editorText != current.editorText else editorDirty,
                                status = "Saved editor buffer · compiling GDScript…"
                            )
                        }
                    }
                }
                val force = SettingsStore.overwrite(getApplication())
                val result = backend.compileAll(
                    File(root, "project").absolutePath,
                    SettingsStore.compressed(getApplication()),
                    SettingsStore.tabSize(getApplication()),
                    force,
                    SettingsStore.continueOnError(getApplication())
                )
                val messages = result.optJSONArray("messages")
                if (messages != null) for (i in 0 until messages.length()) LogStore.core(messages.optString(i))
                val ok = result.optInt("ok")
                val failed = result.optInt("failed")
                withContext(Dispatchers.Main) {
                    mutate { copy(status = "Batch compile: $ok done · $failed failed") }
                    refreshFiles()
                }
                LogStore.core("Batch compile finished: $ok completed, $failed failed.")
            } catch (error: Exception) {
                val cancelled = cancelFile.exists() || error.message?.contains("cancelled", true) == true
                withContext(Dispatchers.Main) { mutate { copy(error = if (cancelled) null else error.message ?: "Batch compilation failed", status = if (cancelled) "Batch compilation cancelled" else status) } }
                LogStore.core("Batch compilation ${if (cancelled) "cancelled" else "failed"}", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun disassembleDex() {
        val current = mutableState.value
        val root = current.workspace ?: return
        if (current.editorDirty && current.selectedFile?.extension == "smali") {
            mutate { copy(error = "Save the open Smali file before regenerating Smali from DEX.") }
            return
        }
        beginOperation("Disassembling DEX into Smali…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val results = SmaliToolchain.disassemble(File(root, "project"), SettingsStore.overwrite(getApplication()))
                results.forEach { LogStore.app(it) }
                withContext(Dispatchers.Main) {
                    mutate { copy(status = "DEX disassembly finished · ${results.size} DEX sets") }
                    refreshFiles()
                }
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "DEX disassembly failed") } }
                LogStore.app("DEX disassembly failed", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun assembleSmali() {
        val current = mutableState.value
        val root = current.workspace ?: return
        beginOperation("Assembling Smali into DEX…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            try {
                flushDirtyEditor(current)
                if (current.editorDirty) withContext(Dispatchers.Main) {
                    mutate { copy(editorDirty = if (selectedFile?.file == current.selectedFile?.file) editorText != current.editorText else editorDirty) }
                }
                val results = SmaliToolchain.assemble(File(root, "project"), SettingsStore.overwrite(getApplication()))
                results.forEach { LogStore.app(it) }
                withContext(Dispatchers.Main) {
                    mutate { copy(status = "Smali assembly finished · ${results.size} DEX sets") }
                    refreshFiles()
                }
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Smali assembly failed") } }
                LogStore.app("Smali assembly failed", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    fun updateBackend(uri: Uri) {
        beginOperation("Validating selected OpenGDS.py backend…", cancelable = false)
        viewModelScope.launch(Dispatchers.IO) {
            val candidate = File(getApplication<Application>().filesDir, "backend/OpenGDS.py.manual.new")
            try {
                FileIntake.copyUri(getApplication(), uri, candidate)
                val api = app.installBackendCandidate(candidate)
                withContext(Dispatchers.Main) { mutate { copy(status = "OpenGDS.py updated successfully · $api") } }
                LogStore.app("Manual OpenGDS.py backend update installed and validated.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Backend update failed", status = "Previous backend retained") } }
                LogStore.app("Backend update rejected; active backend remains in use", error)
            } finally {
                candidate.delete()
                withContext(Dispatchers.Main) { finishOperation() }
            }
        }
    }

    fun exportWorkspace(treeUri: Uri) {
        val current = mutableState.value
        val root = current.workspace ?: return
        beginOperation("Exporting project files to folder…")
        viewModelScope.launch(Dispatchers.IO) {
            try {
                flushDirtyEditor(current)
                val target = DocumentFile.fromTreeUri(getApplication(), treeUri) ?: error("Unable to access destination folder")
                copyFileTreeToDocuments(File(root, "project"), target)
                withContext(Dispatchers.Main) {
                    mutate {
                        copy(
                            editorDirty = if (selectedFile?.file == current.selectedFile?.file) editorText != current.editorText else editorDirty,
                            status = "Project exported to selected folder"
                        )
                    }
                }
                LogStore.app("Workspace ${root.name} exported as project files.")
            } catch (error: Exception) {
                withContext(Dispatchers.Main) { mutate { copy(error = error.message ?: "Export failed") } }
                LogStore.app("Workspace export failed", error)
            } finally { withContext(Dispatchers.Main) { finishOperation() } }
        }
    }

    private fun copyFileTreeToDocuments(source: File, destination: DocumentFile) {
        source.listFiles()?.forEach { file ->
            if (source.name == "project" && file.name == "_pck") return@forEach
            if (!file.isDirectory && (file.name.endsWith(".bak") || file.name.endsWith(".opengds-tmp") || file.name.endsWith(".copying"))) return@forEach
            if (file.isDirectory) {
                val dir = destination.findFile(file.name) ?: destination.createDirectory(file.name)
                if (dir != null) copyFileTreeToDocuments(file, dir)
            } else {
                destination.findFile(file.name)?.delete()
                val out = destination.createFile("application/octet-stream", file.name) ?: error("Cannot create ${file.name}")
                getApplication<Application>().contentResolver.openOutputStream(out.uri, "w")?.use { output ->
                    file.inputStream().use { input -> input.copyTo(output, 128 * 1024) }
                } ?: error("Cannot write ${file.name}")
            }
        }
    }

    fun logUi(message: String) = LogStore.app(message)
}
