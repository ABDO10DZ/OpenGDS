package com.ABDO10DZ.OpenGDS.ui

import android.net.Uri
import android.widget.ImageView
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.material3.RadioButton
import androidx.compose.ui.text.input.PasswordVisualTransformation

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.CancellationException

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Android
import androidx.compose.material.icons.outlined.BugReport
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.DeleteSweep
import androidx.compose.material.icons.outlined.DeleteForever
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.MenuBook
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.Fullscreen
import androidx.compose.material.icons.outlined.FullscreenExit
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontFamily
import java.io.File
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.geometry.Offset
import androidx.compose.foundation.text.input.OutputTransformation
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import kotlinx.coroutines.flow.drop
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt
import com.ABDO10DZ.OpenGDS.core.AppRecord
import com.ABDO10DZ.OpenGDS.core.ApkRecord
import com.ABDO10DZ.OpenGDS.core.ProjectFile
import com.ABDO10DZ.OpenGDS.core.formatBytes
import com.ABDO10DZ.OpenGDS.data.MainPage
import com.ABDO10DZ.OpenGDS.data.OpenGDSViewModel
import com.ABDO10DZ.OpenGDS.core.GodotPckExtractor
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OpenGDSRoot(model: OpenGDSViewModel) {
    val context = LocalContext.current
    val state by model.state.collectAsState()
    val logs by model.logs.collectAsState()
    val clipboard = LocalClipboardManager.current

    val apkPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::importApk) }
    val folderPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri -> uri?.let(model::importFolder) }
    val apkFolderPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri -> uri?.let(model::scanApkFolder) }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> model.importSources(uris) }
    val workspaceApkPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::importAndOpenApk) }
    val replacePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::replaceSelectedFile) }
    val backendPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::updateBackend) }
    val exportPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri -> uri?.let(model::exportWorkspace) }
    var exportAfterFolderSelection by remember { mutableStateOf(false) }
    var showSigningDialog by remember { mutableStateOf(false) }
    var signingMode by remember {
        mutableStateOf(if (state.alwaysUnsignedOutput) "unsigned" else "local")
    }
    var selectedKeystoreUri by remember { mutableStateOf<Uri?>(null) }
    var keystorePassword by remember { mutableStateOf("") }
    var keystoreAlias by remember { mutableStateOf("") }
    var keyPassword by remember { mutableStateOf("") }

    val keystorePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        selectedKeystoreUri = uri
        if (uri != null) runCatching {
            context.contentResolver.takePersistableUriPermission(
                uri,
                android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
        }
    }

    val outputDirectoryPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        if (uri != null) {
            model.setDefaultOutputDirectory(uri)
            if (exportAfterFolderSelection) {
                signingMode = if (state.alwaysUnsignedOutput) "unsigned" else "local"
                showSigningDialog = true
            }
        }
        exportAfterFolderSelection = false
    }
    var addMenuExpanded by remember { mutableStateOf(false) }
    val exportInstallableApk: () -> Unit = {
        signingMode = if (state.alwaysUnsignedOutput) "unsigned" else "local"
        if (state.outputDirectoryConfigured) {
            showSigningDialog = true
        } else {
            exportAfterFolderSelection = true
            outputDirectoryPicker.launch(null)
        }
    }

    LaunchedEffect(Unit) { model.scanAll() }

    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("OpenGDS IDE", style = MaterialTheme.typography.titleLarge)
                        Text("GDSC v101 WORKBENCH", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary, letterSpacing = 1.2.sp)
                    }
                },
                navigationIcon = {
                    Icon(Icons.Outlined.Code, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 16.dp).size(25.dp))
                },
                actions = {
                    if (state.loading) CircularProgressIndicator(Modifier.padding(end = 16.dp).size(20.dp), strokeWidth = 2.dp)
                    else IconButton(onClick = model::scanAll) { Icon(Icons.Outlined.Refresh, "Rescan") }
                },
                colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = MaterialTheme.colorScheme.background)
            )
        },
        floatingActionButton = {
            if (state.page == MainPage.EDITOR) {
                Box {
                    FloatingActionButton(
                        onClick = { addMenuExpanded = true },
                        shape = RoundedCornerShape(18.dp),
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary
                    ) {
                        Icon(Icons.Outlined.Add, contentDescription = "Create or import")
                    }
                    DropdownMenu(
                        expanded = addMenuExpanded,
                        onDismissRequest = { addMenuExpanded = false }
                    ) {
                        DropdownMenuItem(
                            text = { Text("New GDScript") },
                            leadingIcon = { Icon(Icons.Outlined.Code, null) },
                            onClick = { addMenuExpanded = false; model.createNewScript() }
                        )
                        DropdownMenuItem(
                            text = { Text("Import .gd / .gdc files") },
                            leadingIcon = { Icon(Icons.Outlined.UploadFile, null) },
                            onClick = { addMenuExpanded = false; filePicker.launch(arrayOf("*/*")) }
                        )
                        DropdownMenuItem(
                            text = { Text("Import project folder") },
                            leadingIcon = { Icon(Icons.Outlined.FolderOpen, null) },
                            onClick = { addMenuExpanded = false; folderPicker.launch(null) }
                        )
                        DropdownMenuItem(
                            text = { Text("Import APK") },
                            leadingIcon = { Icon(Icons.Outlined.Android, null) },
                            onClick = { addMenuExpanded = false; workspaceApkPicker.launch(arrayOf("application/vnd.android.package-archive", "application/octet-stream", "*/*")) }
                        )
                    }
                }
            }
        },
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                NavigationBarItem(selected = state.page == MainPage.PROJECTS, onClick = { model.navigate(MainPage.PROJECTS) }, icon = { Icon(Icons.Outlined.Android, null) }, label = { Text("Apps") })
                NavigationBarItem(selected = state.page == MainPage.EDITOR, onClick = { model.navigate(MainPage.EDITOR) }, icon = { Icon(Icons.Outlined.Code, null) }, label = { Text("Editor") })
                NavigationBarItem(selected = state.page == MainPage.LOGS, onClick = { model.navigate(MainPage.LOGS) }, icon = { Icon(Icons.Outlined.BugReport, null) }, label = { Text("Logs") })
                NavigationBarItem(selected = state.page == MainPage.SETTINGS, onClick = { model.navigate(MainPage.SETTINGS) }, icon = { Icon(Icons.Outlined.Settings, null) }, label = { Text("Settings") })
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (state.error != null) {
                Surface(color = MaterialTheme.colorScheme.errorContainer, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(state.error ?: "", modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onErrorContainer, style = MaterialTheme.typography.bodySmall)
                        TextButton(onClick = model::dismissError) { Text("Dismiss") }
                    }
                }
            }
            when (state.page) {
                MainPage.PROJECTS -> ProjectsPage(
                    state, model,
                    onAddApk = { apkPicker.launch(arrayOf("*/*")) },
                    onScanApkFolder = { apkFolderPicker.launch(null) },
                    onImportFolder = { folderPicker.launch(null) }
                )
                MainPage.EDITOR -> EditorPage(
                    state, model,
                    onReplaceFile = { replacePicker.launch(arrayOf("*/*")) },
                    onExport = { exportPicker.launch(null) },
                    onExportApk = exportInstallableApk,
                    onCloseProject = model::closeProject,
                    onShareSource = model::shareCurrentSource
                )
                MainPage.LOGS -> LogsPage(logs, onCopy = { clipboard.setText(AnnotatedString(logs.joinToString("\n"))) }, onClear = { model.logUi("Log viewer cleared by user."); com.ABDO10DZ.OpenGDS.core.LogStore.clear() })
                MainPage.SETTINGS -> SettingsPage(
                    state, model,
                    onUpdateBackend = { backendPicker.launch(arrayOf("text/x-python", "text/plain", "*/*")) },
                    onOpenLogs = { model.navigate(MainPage.LOGS) },
                    onChooseOutputDirectory = { exportAfterFolderSelection = false; outputDirectoryPicker.launch(null) },
                    onResetBackend = model::resetBackend,
                    onCleanStorage = model::cleanStorage,
                    onDeleteAllWorkspaceStorage = model::deleteAllWorkspaceStorage,
                    onDeleteImportedApkStorage = model::deleteImportedApkStorage
                )
            }
        }
    }

    if (showSigningDialog) {
        AlertDialog(
            onDismissRequest = {
                showSigningDialog = false
                keystorePassword = ""
                keyPassword = ""
            },
            title = { Text("Choose APK signing method") },
            text = {
                Column(
                    Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(
                            selected = signingMode == "local",
                            onClick = { signingMode = "local" }
                        )
                        Column {
                            Text("OpenGDS local key")
                            Text(
                                "Use OpenGDS' persistent signing certificate.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(
                            selected = signingMode == "jks",
                            onClick = { signingMode = "jks" }
                        )
                        Column {
                            Text("Use my JKS / PKCS12 keystore")
                            Text(
                                "Select .jks, .keystore, .p12 or .pfx.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    if (signingMode == "jks") {
                        OutlinedButton(
                            onClick = {
                                keystorePicker.launch(
                                    arrayOf(
                                        "application/octet-stream",
                                        "application/x-java-keystore",
                                        "*/*"
                                    )
                                )
                            },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                if (selectedKeystoreUri == null)
                                    "Select keystore file"
                                else "Choose another keystore"
                            )
                        }

                        Text(
                            selectedKeystoreUri?.lastPathSegment ?: "No keystore selected",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )

                        OutlinedTextField(
                            value = keystorePassword,
                            onValueChange = { keystorePassword = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("Keystore password") },
                            visualTransformation = PasswordVisualTransformation()
                        )

                        OutlinedTextField(
                            value = keystoreAlias,
                            onValueChange = { keystoreAlias = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("Key alias (optional: auto-detect)") }
                        )

                        OutlinedTextField(
                            value = keyPassword,
                            onValueChange = { keyPassword = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = {
                                Text("Private-key password (blank = keystore password)")
                            },
                            visualTransformation = PasswordVisualTransformation()
                        )
                    }

                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(
                            selected = signingMode == "unsigned",
                            onClick = { signingMode = "unsigned" }
                        )
                        Column {
                            Text("Skip signing")
                            Text(
                                "Export unsigned APKs for later manual signing.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    Text(
                        "Every APK split is signed with the same selected key. " +
                        "Updating an existing app requires its original signing certificate.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            },
            confirmButton = {
                TextButton(
                    enabled = signingMode != "jks" ||
                        (selectedKeystoreUri != null && keystorePassword.isNotEmpty()),
                    onClick = {
                        showSigningDialog = false
                        model.repackApk(
                            signingMode = signingMode,
                            keystoreUri = selectedKeystoreUri,
                            keystorePassword = keystorePassword,
                            keystoreAlias = keystoreAlias,
                            keyPassword = keyPassword
                        )
                        keystorePassword = ""
                        keyPassword = ""
                    }
                ) {
                    Text(if (signingMode == "unsigned") "Export unsigned" else "Sign and export")
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    showSigningDialog = false
                    keystorePassword = ""
                    keyPassword = ""
                }) { Text("Cancel") }
            }
        )
    }

    if (state.loading) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("OpenGDS is working") },
            text = {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    CircularProgressIndicator(Modifier.size(26.dp), strokeWidth = 2.5.dp)
                    Text(state.status, style = MaterialTheme.typography.bodyMedium)
                }
            },
            confirmButton = {
                if (state.canCancelOperation) TextButton(onClick = model::cancelOperation) { Text("Cancel") }
            }
        )
    }

    val updateNotice = state.coreUpdate
    if (updateNotice != null && !state.loading) {
        AlertDialog(
            onDismissRequest = model::dismissCoreUpdate,
            title = { Text("OpenGDS core update available") },
            text = {
                Text("A different OpenGDS.py was found on GitHub and passed compatibility validation. SHA-256: ${updateNotice.sha256.take(24)}…\n\nInstall it now? Your current core is retained if activation fails.")
            },
            confirmButton = { TextButton(onClick = model::installGitHubCoreUpdate) { Text("Update core") } },
            dismissButton = { TextButton(onClick = model::dismissCoreUpdate) { Text("Later") } }
        )
    }
}

@Composable
private fun ProjectsPage(
    state: com.ABDO10DZ.OpenGDS.data.OpenGDSState,
    model: OpenGDSViewModel,
    onAddApk: () -> Unit,
    onScanApkFolder: () -> Unit,
    onImportFolder: () -> Unit
) {
    var compactTab by remember { mutableIntStateOf(0) }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        if (maxWidth >= 760.dp) {
            Row(Modifier.fillMaxSize().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                InstalledPanel(state, model, Modifier.weight(1f))
                ApkPanel(state, model, onAddApk, onScanApkFolder, onImportFolder, Modifier.weight(1f))
            }
        } else {
            Column(Modifier.fillMaxSize().padding(12.dp)) {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SegmentedButton(selected = compactTab == 0, onClick = { compactTab = 0 }, shape = SegmentedButtonDefaults.itemShape(0, 2)) { Text("Installed") }
                    SegmentedButton(selected = compactTab == 1, onClick = { compactTab = 1 }, shape = SegmentedButtonDefaults.itemShape(1, 2)) { Text("APK files") }
                }
                Spacer(Modifier.height(10.dp))
                if (compactTab == 0) InstalledPanel(state, model, Modifier.weight(1f))
                else ApkPanel(state, model, onAddApk, onScanApkFolder, onImportFolder, Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun InstalledPanel(state: com.ABDO10DZ.OpenGDS.data.OpenGDSState, model: OpenGDSViewModel, modifier: Modifier = Modifier) {
    var query by remember { mutableStateOf("") }
    Card(modifier.fillMaxHeight(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.fillMaxSize().padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Installed apps", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                AssistChip(onClick = model::scanAll, label = { Text("${state.installedApps.size}") }, leadingIcon = { Icon(Icons.Outlined.Android, null, Modifier.size(16.dp)) })
            }
            Text("Godot projects are prioritized", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text("Search installed apps") }, leadingIcon = { Icon(Icons.Outlined.Search, null) })
            SettingSwitch("Show system apps", state.showSystemApps, model::setShowSystem, compact = true)
            SettingSwitch("Include non-Godot apps", state.includeNonGodot, model::setIncludeNonGodot, compact = true)
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            if (state.installedApps.isEmpty() && !state.loading) EmptyState("No matching installed apps", "Only Godot apps are listed by default.")
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.weight(1f)) {
                items(state.installedApps.filter { it.label.contains(query, true) || it.packageName.contains(query, true) }, key = { it.packageName }) { app ->
                    AppRow(app) { model.openInstalledApp(app) }
                }
            }
        }
    }
}

@Composable
private fun ApkPanel(
    state: com.ABDO10DZ.OpenGDS.data.OpenGDSState,
    model: OpenGDSViewModel,
    onAddApk: () -> Unit,
    onScanApkFolder: () -> Unit,
    onImportFolder: () -> Unit,
    modifier: Modifier = Modifier
) {
    var query by remember { mutableStateOf("") }
    Card(modifier.fillMaxHeight(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.fillMaxSize().padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("APK workspace", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                IconButton(onClick = onAddApk) { Icon(Icons.Outlined.UploadFile, "Add APK") }
                IconButton(onClick = onScanApkFolder) { Icon(Icons.Outlined.Folder, "Scan APK folder") }
                IconButton(onClick = onImportFolder) { Icon(Icons.Outlined.FolderOpen, "Import project folder") }
            }
            Text("Analyze local APKs and project folders", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, placeholder = { Text("Search APK files") }, leadingIcon = { Icon(Icons.Outlined.Search, null) })
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Show non-Godot APKs", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                Switch(state.includeNonGodot, model::setIncludeNonGodot)
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            if (state.importedApks.isEmpty() && !state.loading) EmptyState("No APKs imported", "Add an APK or import a folder containing .gdc files.")
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.weight(1f)) {
                items(state.importedApks.filter { it.name.contains(query, true) }, key = { it.path }) { apk ->
                    ApkRow(apk) { model.openApk(apk) }
                }
            }
        }
    }
}

@Composable
private fun AppRow(app: AppRecord, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).clickable(onClick = onClick).padding(horizontal = 8.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        AppPackageIcon(app.packageName, app.label)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(app.label, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(app.packageName, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("${app.versionName}${if (app.isSystem) " · System" else ""}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ProjectBadge(if (app.isGodot) "GODOT" else "OTHER", app.isGodot)
    }
}

@Composable
private fun ApkRow(apk: ApkRecord, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).clickable(onClick = onClick).padding(horizontal = 8.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Surface(Modifier.size(40.dp), shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.primaryContainer) {
            Icon(Icons.Outlined.InsertDriveFile, null, Modifier.padding(9.dp), tint = MaterialTheme.colorScheme.primary)
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(apk.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(formatBytes(apk.bytes), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ProjectBadge(if (apk.isGodot) "GODOT" else "OTHER", apk.isGodot)
    }
}

@Composable
private fun AppPackageIcon(packageName: String, label: String) {
    val context = LocalContext.current
    val drawable = remember(packageName) {
        runCatching {
            context.packageManager.getApplicationIcon(packageName)
        }.getOrNull()
    }

    Surface(
        Modifier.size(40.dp),
        shape = RoundedCornerShape(11.dp),
        color = MaterialTheme.colorScheme.primaryContainer
    ) {
        if (drawable != null) {
            AndroidView(
                factory = {
                    ImageView(it).apply {
                        scaleType = ImageView.ScaleType.FIT_CENTER
                    }
                },
                update = { imageView ->
                    imageView.setImageDrawable(drawable)
                },
                modifier = Modifier.fillMaxSize().padding(3.dp)
            )
        } else {
            Box(contentAlignment = Alignment.Center) {
                Text(
                    label.firstOrNull()?.uppercase() ?: "G",
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleMedium
                )
            }
        }
    }
}

@Composable
private fun ProjectBadge(label: String, positive: Boolean) {
    val color = if (positive) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.onSurfaceVariant
    Surface(color = color.copy(alpha = 0.12f), shape = CircleShape) {
        Text(label, Modifier.padding(horizontal = 8.dp, vertical = 4.dp), color = color, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun EmptyState(title: String, detail: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(Icons.Outlined.FolderOpen, null, Modifier.size(32.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(8.dp))
        Text(title, style = MaterialTheme.typography.bodyMedium)
        Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun EditorPage(
    state: com.ABDO10DZ.OpenGDS.data.OpenGDSState,
    model: OpenGDSViewModel,
    onReplaceFile: () -> Unit,
    onExport: () -> Unit,
    onExportApk: () -> Unit,
    onCloseProject: () -> Unit,
    onShareSource: () -> Unit
) {
    val workspace = state.workspace
    var pendingDelete by remember { mutableStateOf<com.ABDO10DZ.OpenGDS.core.RecentWorkspaceEntry?>(null) }
    if (workspace == null) {
        Column(
            Modifier.fillMaxSize().padding(horizontal = 16.dp).verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            EmptyState(
                "Start a GDScript workspace",
                "Tap + to create a script, import .gd/.gdc files, open a project folder, or load an APK. An APK is optional."
            )
            if (state.recentWorkspaces.isNotEmpty()) {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Recent projects", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    Text("${state.recentWorkspaces.size}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                state.recentWorkspaces.forEach { recent ->
                    Card(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, top = 10.dp, bottom = 10.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(
                                Icons.Outlined.FolderOpen,
                                contentDescription = null,
                                tint = if (recent.isAvailable) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                                modifier = Modifier.size(22.dp)
                            )
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(recent.file.name.ifBlank { recent.path }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(
                                    if (recent.isAvailable) recent.path else "Folder unavailable · remove this entry or restore its folder",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = if (recent.isAvailable) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis
                                )
                                Spacer(Modifier.height(6.dp))
                                OutlinedButton(
                                    onClick = { model.openRecentWorkspace(recent.path) },
                                    enabled = !state.loading && recent.isAvailable
                                ) {
                                    Icon(Icons.Outlined.FolderOpen, null, modifier = Modifier.size(16.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("Open project")
                                }
                            }
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                IconButton(
                                    onClick = { pendingDelete = recent },
                                    enabled = !state.loading && recent.file.isDirectory
                                ) {
                                    Icon(Icons.Outlined.DeleteForever, contentDescription = "Delete project and all its files", tint = MaterialTheme.colorScheme.error)
                                }
                                IconButton(
                                    onClick = { model.removeRecentWorkspace(recent.path) },
                                    enabled = !state.loading
                                ) {
                                    Icon(Icons.Outlined.Close, contentDescription = "Remove from recent projects", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
                Text(
                    "Trash permanently deletes the project from OpenGDS storage. Close only removes its history entry.",
                    Modifier.fillMaxWidth().padding(top = 4.dp),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        val item = pendingDelete
        if (item != null) {
            AlertDialog(
                onDismissRequest = { pendingDelete = null },
                title = { Text("Delete project permanently?") },
                text = { Text("${item.file.name} and all files stored inside its OpenGDS workspace will be permanently deleted, including extracted resources, original APKs, and backups. This cannot be undone.") },
                confirmButton = {
                    TextButton(onClick = { pendingDelete = null; model.deleteRecentWorkspaceStorage(item.path) }) {
                        Text("Delete permanently", color = MaterialTheme.colorScheme.error)
                    }
                },
                dismissButton = { TextButton(onClick = { pendingDelete = null }) { Text("Cancel") } }
            )
        }
        return
    }

    var mobileEditorVisible by remember(workspace.absolutePath) { mutableStateOf(state.selectedFile != null && state.selectedFile.extension != "gdc") }
    var editorExpanded by remember(workspace.absolutePath) { mutableStateOf(false) }
    var actionsExpanded by remember(workspace.absolutePath) { mutableStateOf(false) }

    // Decompilation publishes the new .gd file and editor buffer together. Reflect the new
    // selection by switching the phone layout to Editor without a second tap.
    LaunchedEffect(state.selectedFile?.file?.absolutePath, state.selectedFile?.extension) {
        if (state.selectedFile != null && state.selectedFile.extension != "gdc") {
            mobileEditorVisible = true
        }
    }

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val compact = maxWidth < 600.dp
        if (editorExpanded) {
            Column(Modifier.fillMaxSize().padding(horizontal = 10.dp, vertical = 8.dp)) {
                EditorPane(
                    state, model, Modifier.fillMaxSize(),
                    expanded = true,
                    onToggleExpanded = { editorExpanded = false }
                )
            }
        } else {
            Column(Modifier.fillMaxSize().padding(horizontal = 10.dp, vertical = 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(workspace.name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(state.status, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Box {
                        IconButton(onClick = { actionsExpanded = true }, enabled = !state.loading) {
                            Icon(Icons.Outlined.MoreVert, contentDescription = "Editor actions")
                        }
                        val selected = state.selectedFile
                        val canRebuildPck = selected != null && GodotPckExtractor.canRebuild(File(workspace, "project"), selected.file)
                        val canShareSource = selected?.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")
                        DropdownMenu(expanded = actionsExpanded, onDismissRequest = { actionsExpanded = false }) {
                            if (selected?.extension == "gdc") {
                                DropdownMenuItem(
                                    text = { Text("Decompile selected GDC") },
                                    leadingIcon = { Icon(Icons.Outlined.Code, null) },
                                    enabled = selected.validGdc && !state.loading,
                                    onClick = { actionsExpanded = false; model.decompileSelected() }
                                )
                                DropdownMenuItem(text = { Text("Debug GDC (static)") }, leadingIcon = { Icon(Icons.Outlined.BugReport, null) }, enabled = selected.validGdc && !state.loading, onClick = { actionsExpanded = false; model.runReport("dbg") })
                                DropdownMenuItem(text = { Text("Audit GDC") }, leadingIcon = { Icon(Icons.Outlined.BugReport, null) }, enabled = selected.validGdc && !state.loading, onClick = { actionsExpanded = false; model.runReport("audit") })
                                DropdownMenuItem(text = { Text("Extract constants") }, leadingIcon = { Icon(Icons.Outlined.MenuBook, null) }, enabled = selected.validGdc && !state.loading, onClick = { actionsExpanded = false; model.runReport("consts") })
                                DropdownMenuItem(text = { Text("Disassemble GDC") }, leadingIcon = { Icon(Icons.Outlined.Code, null) }, enabled = selected.validGdc && !state.loading, onClick = { actionsExpanded = false; model.runReport("disasm") })
                                DropdownMenuItem(text = { Text("Hex dump") }, leadingIcon = { Icon(Icons.Outlined.Search, null) }, enabled = selected.validGdc && !state.loading, onClick = { actionsExpanded = false; model.runReport("hexdump") })
                                HorizontalDivider()
                            }
                            DropdownMenuItem(
                                text = { Text("Decompile all GDC") },
                                leadingIcon = { Icon(Icons.Outlined.Code, null) },
                                enabled = !state.loading,
                                onClick = { actionsExpanded = false; model.decompileAll() }
                            )
                            DropdownMenuItem(
                                text = { Text("Compile all GD") },
                                leadingIcon = { Icon(Icons.Outlined.Refresh, null) },
                                enabled = !state.loading,
                                onClick = { actionsExpanded = false; model.compileAll() }
                            )
                            DropdownMenuItem(
                                text = { Text("Rebuild embedded PCK") },
                                leadingIcon = { Icon(Icons.Outlined.Folder, null) },
                                enabled = canRebuildPck && !state.loading,
                                onClick = { actionsExpanded = false; model.rebuildPck() }
                            )
                            DropdownMenuItem(
                                text = { Text("Export installable APK(s)") },
                                leadingIcon = { Icon(Icons.Outlined.Android, null) },
                                enabled = File(workspace, "source/base.apk").isFile && !state.loading,
                                onClick = { actionsExpanded = false; onExportApk() }
                            )
                            DropdownMenuItem(
                                text = { Text("Export project files") },
                                leadingIcon = { Icon(Icons.Outlined.Download, null) },
                                enabled = !state.loading,
                                onClick = { actionsExpanded = false; onExport() }
                            )
                            DropdownMenuItem(
                                text = { Text("Share current source") },
                                leadingIcon = { Icon(Icons.Outlined.Share, null) },
                                enabled = canShareSource && !state.loading,
                                onClick = { actionsExpanded = false; onShareSource() }
                            )
                            DropdownMenuItem(
                                text = { Text("Replace selected file") },
                                leadingIcon = { Icon(Icons.Outlined.UploadFile, null) },
                                enabled = selected != null && !state.loading,
                                onClick = { actionsExpanded = false; onReplaceFile() }
                            )
                            DropdownMenuItem(text = { Text("DEX → Smali") }, leadingIcon = { Icon(Icons.Outlined.Code, null) }, enabled = !state.loading, onClick = { actionsExpanded = false; model.disassembleDex() })
                            DropdownMenuItem(text = { Text("Smali → DEX") }, leadingIcon = { Icon(Icons.Outlined.Refresh, null) }, enabled = !state.loading, onClick = { actionsExpanded = false; model.assembleSmali() })
                            HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("Close project") },
                                leadingIcon = { Icon(Icons.Outlined.Close, null) },
                                enabled = !state.loading,
                                onClick = { actionsExpanded = false; onCloseProject() }
                            )
                        }
                    }
                }
                HorizontalDivider(Modifier.padding(vertical = 7.dp))
                if (compact) {
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                        SegmentedButton(
                            selected = !mobileEditorVisible,
                            onClick = { mobileEditorVisible = false },
                            shape = SegmentedButtonDefaults.itemShape(0, 2)
                        ) { Text("Files") }
                        SegmentedButton(
                            selected = mobileEditorVisible,
                            onClick = { mobileEditorVisible = true },
                            shape = SegmentedButtonDefaults.itemShape(1, 2)
                        ) { Text("Editor") }
                    }
                    Spacer(Modifier.height(7.dp))
                    if (mobileEditorVisible) {
                        EditorPane(
                            state, model, Modifier.fillMaxWidth().weight(1f),
                            expanded = false,
                            onToggleExpanded = { editorExpanded = true }
                        )
                    } else {
                        FileBrowser(
                            state.projectFiles, state.selectedFile, model,
                            Modifier.fillMaxWidth().weight(1f),
                            onFileOpen = { mobileEditorVisible = true }
                        )
                    }
                } else {
                    Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                        FileBrowser(state.projectFiles, state.selectedFile, model, Modifier.weight(0.34f).fillMaxHeight(), onFileOpen = {})
                        VerticalSeparator()
                        EditorPane(
                            state, model, Modifier.weight(0.66f).fillMaxHeight(),
                            expanded = false,
                            onToggleExpanded = { editorExpanded = true }
                        )
                    }
                }
            }
        }
    }
}

private class ProjectTreeNode(
    val name: String,
    val relativePath: String,
    val file: ProjectFile? = null
) {
    val children = mutableListOf<ProjectTreeNode>()
    val isDirectory: Boolean get() = file == null
}

private data class VisibleTreeRow(val node: ProjectTreeNode, val depth: Int)

private fun buildProjectTree(files: List<ProjectFile>): List<ProjectTreeNode> {
    val roots = mutableListOf<ProjectTreeNode>()
    val directories = linkedMapOf<String, ProjectTreeNode>()
    files.forEach { file ->
        val parts = file.relativePath.split('/').filter { it.isNotBlank() }
        var parentPath = ""
        var parentChildren = roots
        parts.dropLast(1).forEach { segment ->
            val path = if (parentPath.isBlank()) segment else "$parentPath/$segment"
            val node = directories.getOrPut(path) {
                ProjectTreeNode(segment, path).also { parentChildren.add(it) }
            }
            parentPath = path
            parentChildren = node.children
        }
        val leafName = parts.lastOrNull() ?: file.file.name
        parentChildren += ProjectTreeNode(leafName, file.relativePath, file)
    }
    fun sort(nodes: MutableList<ProjectTreeNode>) {
        nodes.sortWith(compareBy<ProjectTreeNode>({ !it.isDirectory }, { it.name.lowercase() }))
        nodes.filter { it.isDirectory }.forEach { sort(it.children) }
    }
    sort(roots)
    return roots
}

private fun flattenVisibleTree(
    nodes: List<ProjectTreeNode>,
    expanded: Set<String>,
    forceExpanded: Boolean
): List<VisibleTreeRow> {
    val rows = mutableListOf<VisibleTreeRow>()
    fun visit(items: List<ProjectTreeNode>, depth: Int) {
        items.forEach { node ->
            rows += VisibleTreeRow(node, depth)
            if (node.isDirectory && (forceExpanded || node.relativePath in expanded)) visit(node.children, depth + 1)
        }
    }
    visit(nodes, 0)
    return rows
}

private data class ContentSearchHit(val file: ProjectFile, val line: Int, val preview: String)
private val CONTENT_EXTENSIONS = setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")
private const val CONTENT_LIMIT_BYTES = 8L * 1024L * 1024L
private const val CONTENT_LIMIT_RESULTS = 500

@Composable
private fun FileBrowser(
    files: List<ProjectFile>, selected: ProjectFile?, model: OpenGDSViewModel,
    modifier: Modifier = Modifier, onFileOpen: () -> Unit = {}
) {
    var query by remember { mutableStateOf("") }
    var showAllFiles by remember { mutableStateOf(false) }
    var regexMode by remember { mutableStateOf(false) }
    var contentMode by remember { mutableStateOf(false) }
    var allTextFiles by remember { mutableStateOf(false) }
    var caseSensitive by remember { mutableStateOf(true) }
    var expanded by remember(files) { mutableStateOf(emptySet<String>()) }
    var hits by remember { mutableStateOf<List<ContentSearchHit>>(emptyList()) }
    var totalHits by remember { mutableIntStateOf(0) }
    var skippedFiles by remember { mutableIntStateOf(0) }
    var searching by remember { mutableStateOf(false) }

    val pattern = remember(query, regexMode) {
        if (query.isBlank()) null else runCatching {
            if (regexMode) Regex(query, RegexOption.IGNORE_CASE)
            else Regex(Regex.escape(query), RegexOption.IGNORE_CASE)
        }.getOrNull()
    }
    val filtered = remember(files, query, showAllFiles, pattern) {
        files.asSequence()
            .filter { showAllFiles || it.extension in setOf("gdc", "gd") }
            .filter { query.isBlank() || pattern?.containsMatchIn(it.relativePath) == true }
            .toList()
    }
    val tree = remember(filtered) { buildProjectTree(filtered) }
    val visibleRows = remember(tree, expanded, query, pattern) {
        flattenVisibleTree(tree, expanded, forceExpanded = query.isNotBlank() && pattern != null)
    }

    LaunchedEffect(contentMode, query, files, allTextFiles, caseSensitive) {
        if (!contentMode || query.isBlank()) {
            hits = emptyList()
            totalHits = 0
            skippedFiles = 0
            searching = false
            return@LaunchedEffect
        }
        searching = true
        delay(250)
        val result = withContext(Dispatchers.IO) {
            val found = mutableListOf<ContentSearchHit>()
            var count = 0
            var skipped = 0
            val coroutineContext = currentCoroutineContext()
            val extensions = if (allTextFiles) CONTENT_EXTENSIONS else setOf("gd")
            val candidates = files.filter { it.extension in extensions }

            for (file in candidates) {
                coroutineContext.ensureActive()
                if (file.bytes > CONTENT_LIMIT_BYTES) {
                    skipped++
                    continue
                }
                try {
                    file.file.bufferedReader(Charsets.UTF_8).use { reader ->
                        var lineNo = 0
                        while (true) {
                            coroutineContext.ensureActive()
                            val line = reader.readLine() ?: break
                            lineNo++
                            if (line.contains(query, ignoreCase = !caseSensitive)) {
                                count++
                                if (found.size < CONTENT_LIMIT_RESULTS) {
                                    val trimmed = line.trim()
                                    found += ContentSearchHit(
                                        file, lineNo,
                                        if (trimmed.length > 200) trimmed.take(197) + "…" else trimmed
                                    )
                                }
                            }
                        }
                    }
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    skipped++
                }
            }
            Triple(found, count, skipped)
        }
        hits = result.first
        totalHits = result.second
        skippedFiles = result.third
        searching = false
    }

    Column(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Folder, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(19.dp))
            Spacer(Modifier.width(6.dp))
            Text("Project files", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.weight(1f))
            Text(
                if (contentMode) "$totalHits match(es)" else "${filtered.size}/${files.size}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Spacer(Modifier.height(6.dp))
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            SegmentedButton(!contentMode, { contentMode = false }, SegmentedButtonDefaults.itemShape(0, 2)) { Text("Names") }
            SegmentedButton(contentMode, { contentMode = true }, SegmentedButtonDefaults.itemShape(1, 2)) { Text("Inside files") }
        }
        Spacer(Modifier.height(5.dp))
        OutlinedTextField(
            query, { query = it }, Modifier.fillMaxWidth(), singleLine = true,
            placeholder = { Text(if (contentMode) "Search text inside files" else "Find file by name") },
            textStyle = MaterialTheme.typography.bodySmall,
            leadingIcon = { Icon(Icons.Outlined.Search, null, Modifier.size(17.dp)) }
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (contentMode) {
                TextButton(onClick = { allTextFiles = !allTextFiles }) {
                    Text(if (allTextFiles) "All text files" else "Only *.gd")
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { caseSensitive = !caseSensitive }) {
                    Text(if (caseSensitive) "Case sensitive" else "Ignore case")
                }
            } else {
                TextButton(onClick = { showAllFiles = !showAllFiles }) {
                    Text(if (showAllFiles) "GDC/GD only" else "Show all files")
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { regexMode = !regexMode }) {
                    Text(if (regexMode) "Regex ✓" else ".* Regex")
                }
            }
        }
        if (contentMode && query.isNotBlank()) {
            Text(
                when {
                    searching -> "Searching recursively…"
                    skippedFiles > 0 -> "$totalHits match(es) · $skippedFiles large/unreadable file(s) skipped"
                    totalHits > CONTENT_LIMIT_RESULTS -> "$totalHits match(es) · showing first $CONTENT_LIMIT_RESULTS"
                    else -> "Literal search · ${if (caseSensitive) "case-sensitive" else "case-insensitive"} · ${if (allTextFiles) "all text files" else "*.gd"}"
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (!contentMode && query.isNotBlank() && pattern == null) {
            Text("Invalid regular expression", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall)
        }
        HorizontalDivider(Modifier.padding(vertical = 3.dp))

        if (contentMode) {
            when {
                query.isBlank() -> EmptyState(
                    "Search inside project files",
                    "Enter literal text. This recursively searches *.gd by default, similar to grep -RnF."
                )
                searching && hits.isEmpty() -> EmptyState("Searching…", "Scanning source files.")
                hits.isEmpty() -> EmptyState("No content matches", "Try another string or enable All text files.")
                else -> LazyColumn(
                    Modifier.weight(1f).fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    items(hits, key = { "${it.file.relativePath}:${it.line}" }) { hit ->
                        Column(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(MaterialTheme.colorScheme.surface)
                                .clickable {
                                    model.openProjectFile(hit.file, hit.line)
                                    onFileOpen()
                                }
                                .padding(horizontal = 8.dp, vertical = 7.dp),
                            verticalArrangement = Arrangement.spacedBy(3.dp)
                        ) {
                            Text(
                                "${hit.file.relativePath}:${hit.line}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.primary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                hit.preview,
                                style = MaterialTheme.typography.bodySmall,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }
                }
            }
        } else if (filtered.isEmpty()) {
            EmptyState(
                "No matching files",
                if (showAllFiles) "Try another name or pattern."
                else "Only .gdc and .gd files are shown. Use Show all files to reveal other file types."
            )
        } else {
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(2.dp)
            ) {
                items(visibleRows, key = { it.node.relativePath }) { row ->
                    val node = row.node
                    val file = node.file
                    val active = file != null && selected?.file == file.file
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(
                                if (active) MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
                                else MaterialTheme.colorScheme.surface
                            )
                            .clickable {
                                if (file == null) {
                                    expanded = if (node.relativePath in expanded)
                                        expanded - node.relativePath else expanded + node.relativePath
                                } else {
                                    model.openProjectFile(file)
                                    onFileOpen()
                                }
                            }
                            .padding(start = (6 + row.depth * 14).dp, end = 7.dp, top = 8.dp, bottom = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (file == null) {
                            Icon(
                                if (node.relativePath in expanded || (query.isNotBlank() && pattern != null))
                                    Icons.Outlined.FolderOpen else Icons.Outlined.Folder,
                                null, Modifier.size(17.dp),
                                tint = MaterialTheme.colorScheme.primary
                            )
                        } else {
                            val icon = when (file.extension) {
                                "gdc" -> Icons.Outlined.Lock
                                "gd" -> Icons.Outlined.Code
                                "smali" -> Icons.Outlined.MenuBook
                                else -> Icons.Outlined.InsertDriveFile
                            }
                            Icon(
                                icon, null, Modifier.size(16.dp),
                                tint = if (file.extension == "gdc") MaterialTheme.colorScheme.secondary
                                else MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Spacer(Modifier.width(6.dp))
                        Column(Modifier.weight(1f)) {
                            Text(node.name, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(
                                if (file == null) "${node.children.size} item(s)"
                                else "${file.extension.uppercase().ifBlank { "FILE" }} · ${formatBytes(file.bytes)}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1
                            )
                        }
                        if (file == null) {
                            Text(if (node.relativePath in expanded) "−" else "+", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VerticalSeparator() {
    Box(Modifier.width(1.dp).fillMaxHeight().background(MaterialTheme.colorScheme.outlineVariant))
}

@Composable
private fun EditorPane(
    state: com.ABDO10DZ.OpenGDS.data.OpenGDSState,
    model: OpenGDSViewModel,
    modifier: Modifier = Modifier,
    expanded: Boolean = false,
    onToggleExpanded: () -> Unit = {}
) {
    val file = state.selectedFile
    if (file == null) {
        Box(modifier, contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Outlined.Code, null, Modifier.size(38.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.height(8.dp))
                Text("Select a source file", style = MaterialTheme.typography.titleSmall)
                Text("GDC files are locked until decompiled.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        return
    }
    if (file.extension == "gdc") {
        Column(modifier) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(file.file.name, style = MaterialTheme.typography.titleSmall)
                    Text(
                        if (file.validGdc) "GDSC v101 · read-only binary" else "Unsupported or invalid GDC",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (file.validGdc) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.error
                    )
                }
                IconButton(onClick = onToggleExpanded) {
                    Icon(if (expanded) Icons.Outlined.FullscreenExit else Icons.Outlined.Fullscreen, contentDescription = if (expanded) "Exit full editor" else "Expand editor")
                }
                Button(onClick = model::decompileSelected, enabled = file.validGdc && !state.loading) { Text("Decompile") }
            }
            HorizontalDivider(Modifier.padding(vertical = 7.dp))
            SelectionContainer {
                Text(
                    state.fileInfo.ifBlank { "Valid GDSC v101 file. Decompile it to create an editable GDScript source file." },
                    Modifier.weight(1f).verticalScroll(rememberScrollState()),
                    style = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 16.sp, color = MaterialTheme.colorScheme.onSurface)
                )
            }
        }
        return
    }

    val editable = file.extension in setOf("gd", "smali", "txt", "json", "xml", "cfg", "tscn", "tres", "gdshader", "md", "ini", "csv")
    var search by remember(file.file.absolutePath) { mutableStateOf("") }
    var searchRegex by remember(file.file.absolutePath) { mutableStateOf(false) }
    val searchPattern = remember(search, searchRegex) {
        if (search.isBlank()) null else runCatching {
            if (searchRegex) Regex(search, RegexOption.IGNORE_CASE)
            else Regex(Regex.escape(search), RegexOption.IGNORE_CASE)
        }.getOrNull()
    }
    val searchMatches = remember(searchPattern, state.editorText) {
        searchPattern?.findAll(state.editorText)?.filter { it.value.isNotEmpty() }
            ?.map { TextRange(it.range.first, it.range.last + 1) }?.toList().orEmpty()
    }
    var activeSearchIndex by remember(file.file.absolutePath, search, searchRegex) { mutableIntStateOf(-1) }
    var searchTarget by remember(file.file.absolutePath) { mutableStateOf<TextRange?>(null) }
    var searchRequestId by remember(file.file.absolutePath) { mutableIntStateOf(0) }
    LaunchedEffect(search, searchRegex, state.editorText) {
        activeSearchIndex = -1
        searchTarget = null
    }
    fun navigateSearch(forward: Boolean) {
        if (searchMatches.isEmpty()) return
        val next = when {
            activeSearchIndex < 0 -> if (forward) 0 else searchMatches.lastIndex
            forward -> (activeSearchIndex + 1) % searchMatches.size
            else -> (activeSearchIndex - 1 + searchMatches.size) % searchMatches.size
        }
        activeSearchIndex = next
        searchTarget = searchMatches[next]
        searchRequestId++
    }
    Column(modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(file.file.name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val editorLabel = when (file.extension) {
                    "smali" -> "Smali source · editable"
                    "gd" -> "GDScript source · editable"
                    else -> "Text file · editable"
                }
                Text(editorLabel, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
            }
            IconButton(onClick = onToggleExpanded) {
                Icon(if (expanded) Icons.Outlined.FullscreenExit else Icons.Outlined.Fullscreen, contentDescription = if (expanded) "Exit full editor" else "Expand editor")
            }
            if (file.extension == "gd") {
                Button(onClick = model::compileSelected, enabled = !state.loading) { Text("Compile") }
            }
            Spacer(Modifier.width(5.dp))
            OutlinedButton(onClick = model::saveEditor, enabled = editable && state.editorDirty && !state.loading) { Text("Save") }
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                search, { search = it }, Modifier.weight(1f), singleLine = true,
                placeholder = { Text("Find in file") }, textStyle = MaterialTheme.typography.bodySmall,
                leadingIcon = { Icon(Icons.Outlined.Search, null) }
            )
            TextButton(onClick = { navigateSearch(false) }, enabled = searchMatches.isNotEmpty()) { Text("Prev") }
            TextButton(onClick = { navigateSearch(true) }, enabled = searchMatches.isNotEmpty()) { Text("Next") }
            TextButton(onClick = { searchRegex = !searchRegex }) { Text(if (searchRegex) "Regex ✓" else ".*") }
        }
        if (!editable) {
            Text(state.fileInfo, modifier = Modifier.weight(1f).padding(10.dp), style = MaterialTheme.typography.bodySmall)
        } else {
            if (search.isNotBlank()) {
                val matches = searchMatches.size
                Text(
                    when {
                        searchPattern == null -> "Invalid regular expression"
                        matches == 0 -> "0 matches"
                        activeSearchIndex >= 0 -> "${activeSearchIndex + 1} of $matches matches"
                        else -> "$matches matches · use Prev / Next to jump"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (searchPattern == null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            CodeEditor(
                fileKey = file.file.absolutePath,
                text = state.editorText,
                onTextChange = model::updateEditor,
                language = when (file.extension) { "smali" -> "smali"; "gd" -> "gd"; else -> "plain" },
                searchTerm = search,
                searchRegex = searchRegex,
                searchTarget = searchTarget,
                searchRequestId = searchRequestId,
                jumpToLine = state.editorJumpToLine,
                jumpRequestId = state.editorJumpRequestId,
                modifier = Modifier.weight(1f).fillMaxWidth()
            )
            if (state.editorDirty) Text("Unsaved changes", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.tertiary)
            if (file.extension == "gd") Text("Compile output: ${file.file.nameWithoutExtension}.gdc · v101", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CodeEditor(
    fileKey: String,
    text: String,
    onTextChange: (String) -> Unit,
    language: String,
    searchTerm: String = "",
    searchRegex: Boolean = false,
    searchTarget: TextRange? = null,
    searchRequestId: Int = 0,
    jumpToLine: Int = 0,
    jumpRequestId: Int = 0,
    modifier: Modifier = Modifier
) {
    // The same scroll state drives BasicTextField and the line-number gutter. This avoids
    // competing nested scroll containers, which previously let the text move without its gutter.
    val editorState = remember(fileKey) { TextFieldState(initialText = text) }
    val editorScrollState = remember(fileKey) { androidx.compose.foundation.ScrollState(0) }
    val textLayoutResult = remember(fileKey) { mutableStateOf<TextLayoutResult?>(null) }
    val latestOnTextChange by rememberUpdatedState(onTextChange)
    val density = LocalDensity.current
    val lineHeight = 18.sp
    val lineHeightPx = with(density) { lineHeight.toPx() }

    // Keep external editor state (save/compile/view-model changes) synchronized with the field.
    LaunchedEffect(fileKey) {
        editorState.edit { selection = TextRange(0) }
        editorScrollState.scrollTo(0)
    }
    LaunchedEffect(text, editorState) {
        if (editorState.text.toString() != text) {
            editorState.setTextAndPlaceCursorAtEnd(text)
            editorState.edit { selection = TextRange(0) }
            withFrameNanos { }
            editorScrollState.scrollTo(0)
        }
    }
    LaunchedEffect(editorState) {
        snapshotFlow { editorState.text.toString() }
            .drop(1)
            .collect { updated -> latestOnTextChange(updated) }
    }

    // Restore the lightweight, delta-based GDScript delimiter helper.
    // It only transforms single-character insertions/deletions; paste and selections stay native.
    val inputTransformation = remember(language) {
        if (language == "gd") gdAutoPairInputTransformation() else null
    }
    val visualSyntax = syntaxTransformation(language, searchTerm, searchRegex, searchTarget)
    val outputTransformation = remember(visualSyntax) {
        OutputTransformation {
            // Reuse the existing token/search highlighter while keeping the text buffer unchanged.
            val styled = visualSyntax.filter(AnnotatedString(toString())).text
            styled.spanStyles.forEach { range ->
                val start = range.start.coerceIn(0, length)
                val end = range.end.coerceIn(start, length)
                if (end > start) addStyle(range.item, start, end)
            }
        }
    }

    val currentText = editorState.text.toString()
    // Newline offsets let the gutter map wrapped visual rows back to real source lines.
    val newlineOffsets = remember(currentText) {
        currentText.indices.filter { currentText[it] == '\n' }.toIntArray()
    }
    val lines = newlineOffsets.size + 1
    val gutterWidth = (lines.toString().length * 8 + 14).dp
    val gutterTextMeasurer = rememberTextMeasurer()
    val gutterTextStyle = TextStyle(
        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f),
        fontFamily = FontFamily.Monospace,
        fontSize = 12.sp,
        lineHeight = lineHeight
    )

    LaunchedEffect(searchRequestId, searchTarget, editorState) {
        val target = searchTarget ?: return@LaunchedEffect
        val safeStart = target.start.coerceIn(0, editorState.text.length)
        val safeEnd = target.end.coerceIn(safeStart, editorState.text.length)
        editorState.edit { selection = TextRange(safeStart, safeEnd) }
        // Wait for the updated layout so wrapped lines do not skew the scroll target.
        withFrameNanos { }
        withFrameNanos { }
        val visualLine = textLayoutResult.value?.getLineForOffset(safeStart)
        val lineTop = visualLine?.let { textLayoutResult.value?.getLineTop(it) }
            ?: (currentText.take(safeStart).count { it == '\n' } * lineHeightPx)
        val destination = (lineTop - lineHeightPx * 2f)
            .roundToInt().coerceIn(0, editorScrollState.maxValue)
        editorScrollState.animateScrollTo(destination)
    }

    LaunchedEffect(jumpRequestId, jumpToLine, editorState) {
        if (jumpRequestId <= 0 || jumpToLine <= 0) return@LaunchedEffect
        var offset = 0
        repeat(jumpToLine - 1) {
            val newline = currentText.indexOf('\n', offset)
            if (newline < 0) return@LaunchedEffect
            offset = newline + 1
        }
        editorState.edit { selection = TextRange(offset.coerceIn(0, editorState.text.length)) }
        withFrameNanos { }
        withFrameNanos { }
        val visualLine = textLayoutResult.value?.getLineForOffset(offset)
        val lineTop = visualLine?.let { textLayoutResult.value?.getLineTop(it) }
            ?: ((jumpToLine - 1) * lineHeightPx)
        val destination = (lineTop - lineHeightPx * 2f)
            .roundToInt().coerceIn(0, editorScrollState.maxValue)
        editorScrollState.animateScrollTo(destination)
    }

    Surface(
        modifier.fillMaxSize(),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    ) {
        Row(
            Modifier.fillMaxSize().padding(8.dp),
            verticalAlignment = Alignment.Top
        ) {
            // Clip the gutter to the viewport and offset it by the text field's actual scroll.
            Canvas(
                Modifier.width(gutterWidth).fillMaxHeight().clipToBounds()
            ) {
                // Use the actual BasicTextField layout, not a guessed line-height / scroll
                // division. This keeps the gutter correct when a long source line wraps.
                val sourceLayout = textLayoutResult.value ?: return@Canvas
                val scrollY = editorScrollState.value.toFloat()
                val firstVisualLine = sourceLayout.getLineForVerticalPosition(scrollY)
                val lastVisualLine = sourceLayout.getLineForVerticalPosition(scrollY + size.height)
                for (visualLine in firstVisualLine..lastVisualLine) {
                    val startOffset = sourceLayout.getLineStart(visualLine)
                    val startsLogicalLine = startOffset == 0 || currentText.getOrNull(startOffset - 1) == '\n'
                    if (!startsLogicalLine) continue // continuation of a wrapped source line

                    val found = newlineOffsets.binarySearch(startOffset)
                    val precedingNewlines = if (found >= 0) found else -found - 1
                    val lineNumber = precedingNewlines + 1
                    val layout = gutterTextMeasurer.measure(
                        text = lineNumber.toString(),
                        style = gutterTextStyle,
                        maxLines = 1,
                        softWrap = false
                    )
                    drawText(
                        textLayoutResult = layout,
                        topLeft = Offset(
                            x = size.width - layout.size.width,
                            y = sourceLayout.getLineTop(visualLine) - scrollY
                        )
                    )
                }
            }
            BasicTextField(
                state = editorState,
                modifier = Modifier.weight(1f).fillMaxHeight(),
                textStyle = TextStyle(
                    color = MaterialTheme.colorScheme.onSurface,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    lineHeight = lineHeight
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
                inputTransformation = inputTransformation,
                outputTransformation = outputTransformation,
                onTextLayout = { getResult -> textLayoutResult.value = getResult() },
                scrollState = editorScrollState,
                decorator = { inner ->
                    Box {
                        if (currentText.isEmpty() && language != "plain") Text(
                            if (language == "smali") "# Smali source" else "# GDScript source",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp
                        )
                        inner()
                    }
                }
            )
        }
    }
}

@Composable
private fun SettingsPage(
    state: com.ABDO10DZ.OpenGDS.data.OpenGDSState,
    model: OpenGDSViewModel,
    onUpdateBackend: () -> Unit,
    onOpenLogs: () -> Unit,
    onChooseOutputDirectory: () -> Unit,
    onResetBackend: () -> Unit,
    onCleanStorage: () -> Unit,
    onDeleteAllWorkspaceStorage: () -> Unit,
    onDeleteImportedApkStorage: () -> Unit
) {
    var showResetConfirmation by remember { mutableStateOf(false) }
    var showCleanupConfirmation by remember { mutableStateOf(false) }
    var showDeleteAllProjectsConfirmation by remember { mutableStateOf(false) }
    var showDeleteImportedApksConfirmation by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().padding(horizontal = 18.dp, vertical = 10.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Appearance", style = MaterialTheme.typography.titleMedium)
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            listOf("system", "light", "dark").forEachIndexed { index, theme ->
                SegmentedButton(selected = state.theme == theme, onClick = { model.setTheme(theme) }, shape = SegmentedButtonDefaults.itemShape(index, 3)) { Text(theme.replaceFirstChar { it.uppercase() }) }
            }
        }
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("Discovery", style = MaterialTheme.typography.titleMedium)
        SettingSwitch("Show system apps", state.showSystemApps, model::setShowSystem)
        SettingSwitch("Include non-Godot apps", state.includeNonGodot, model::setIncludeNonGodot)
        Text("Godot applications and GDSC v101 remain the default focus. Non-Godot visibility enables Smali text editing for imported source files.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("Compilation", style = MaterialTheme.typography.titleMedium)
        SettingSwitch("Zstandard compression", state.compressed, model::setCompressed)
        SettingSwitch("Replace existing .gd/.gdc outputs", state.overwrite, model::setOverwrite)
        Text("When enabled, imports and generated .gd/.gdc outputs can replace same-name files; the previous file is kept as a .bak backup.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        SettingSwitch("Continue after batch errors", state.continueOnError, model::setContinueOnError)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Tab width", style = MaterialTheme.typography.bodyMedium)
                Text("Used when tokenizing GDScript source", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            OutlinedButton(onClick = { model.setTabSize(if (state.tabSize >= 8) 2 else state.tabSize + 2) }) { Text("${state.tabSize} spaces") }
        }
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("APK repacking", style = MaterialTheme.typography.titleMedium)
        Text(
            if (state.outputDirectoryConfigured) "Default output folder is configured." else "Choose where rebuilt APK files will be saved.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OutlinedButton(onClick = onChooseOutputDirectory, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.FolderOpen, null)
            Spacer(Modifier.width(8.dp))
            Text("Choose default APK output folder")
        }
        SettingSwitch("Default to unsigned in export dialog", state.alwaysUnsignedOutput, model::setAlwaysUnsignedOutput)
        Text(
            if (state.alwaysUnsignedOutput) "This is the default selection in the export dialog. You can instead use OpenGDS local signing or select your own JKS/PKCS12 keystore each time."
            else "OpenGDS signs exports with a persistent local key. This certificate is different from the original app developer's certificate; use your own keystore when the original signing identity must be preserved.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text("Split apps export as one XAPK with base.apk and every split. Install it using an XAPK-compatible installer that installs all parts together.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("Backend", style = MaterialTheme.typography.titleMedium)
        Text("Once per app launch, OpenGDS checks GitHub when a validated internet connection is available. It compares SHA-256 and validates a changed core before offering an update; installation always requires your approval.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Button(onClick = onUpdateBackend, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.UploadFile, null)
            Spacer(Modifier.width(8.dp))
            Text("Update OpenGDS.py manually")
        }
        OutlinedButton(onClick = { showResetConfirmation = true }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.Refresh, null)
            Spacer(Modifier.width(8.dp))
            Text("Reset OpenGDS.py to bundled core")
        }
        OutlinedButton(onClick = { showCleanupConfirmation = true }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.DeleteSweep, null)
            Spacer(Modifier.width(8.dp))
            Text("Clean temporary OpenGDS storage")
        }
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) {
            Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text("Storage used by OpenGDS IDE", style = MaterialTheme.typography.titleSmall)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Saved project workspaces (includes source APKs)", style = MaterialTheme.typography.bodySmall)
                    Text(formatBytes(state.storageUsage.projectsBytes), style = MaterialTheme.typography.bodySmall)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Separately imported APK library", style = MaterialTheme.typography.bodySmall)
                    Text(formatBytes(state.storageUsage.importedApksBytes), style = MaterialTheme.typography.bodySmall)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Temporary and code cache", style = MaterialTheme.typography.bodySmall)
                    Text(formatBytes(state.storageUsage.cacheBytes), style = MaterialTheme.typography.bodySmall)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Python core", style = MaterialTheme.typography.bodySmall)
                    Text(formatBytes(state.storageUsage.backendBytes), style = MaterialTheme.typography.bodySmall)
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Other app data", style = MaterialTheme.typography.bodySmall)
                    Text(formatBytes(state.storageUsage.otherAppDataBytes), style = MaterialTheme.typography.bodySmall)
                }
                HorizontalDivider(Modifier.padding(vertical = 3.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Total tracked", style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                    Text(formatBytes(state.storageUsage.totalBytes), style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                }
                Text("Temporary cleanup removes cache and abandoned files. Saved projects are preserved and can be deleted individually from Editor → Recent projects.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        OutlinedButton(onClick = { showDeleteAllProjectsConfirmation = true }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.DeleteForever, null, tint = MaterialTheme.colorScheme.error)
            Spacer(Modifier.width(8.dp))
            Text("Delete all saved projects", color = MaterialTheme.colorScheme.error)
        }
        OutlinedButton(onClick = { showDeleteImportedApksConfirmation = true }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.DeleteForever, null, tint = MaterialTheme.colorScheme.error)
            Spacer(Modifier.width(8.dp))
            Text("Delete imported APK library", color = MaterialTheme.colorScheme.error)
        }
        OutlinedButton(onClick = onOpenLogs, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.BugReport, null)
            Spacer(Modifier.width(8.dp))
            Text("Open log viewer")
        }
        HorizontalDivider(Modifier.padding(vertical = 4.dp))
        Text("Developer: 0xbytecode", style = MaterialTheme.typography.labelLarge)
        Text("Version: 1.0.3", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(10.dp))
    }
    if (showResetConfirmation) {
        AlertDialog(
            onDismissRequest = { showResetConfirmation = false },
            title = { Text("Restore bundled core?") },
            text = { Text("The currently selected OpenGDS.py will be replaced by the built-in version. Your projects and APK files are not affected.") },
            confirmButton = { TextButton(onClick = { showResetConfirmation = false; onResetBackend() }) { Text("Reset core") } },
            dismissButton = { TextButton(onClick = { showResetConfirmation = false }) { Text("Cancel") } }
        )
    }
    if (showCleanupConfirmation) {
        AlertDialog(
            onDismissRequest = { showCleanupConfirmation = false },
            title = { Text("Clean temporary storage?") },
            text = { Text("Temporary files and application cache will be removed. Saved workspaces, original APKs, project resources, backups, and the active Python core will be kept.") },
            confirmButton = { TextButton(onClick = { showCleanupConfirmation = false; onCleanStorage() }) { Text("Clean temporary files") } },
            dismissButton = { TextButton(onClick = { showCleanupConfirmation = false }) { Text("Cancel") } }
        )
    }
    if (showDeleteAllProjectsConfirmation) {
        AlertDialog(
            onDismissRequest = { showDeleteAllProjectsConfirmation = false },
            title = { Text("Delete all saved projects?") },
            text = { Text("This permanently deletes every OpenGDS workspace, including imported APKs, extracted project resources, generated files, and backups. The current open project and recent-project history will also be cleared. This cannot be undone.") },
            confirmButton = {
                TextButton(onClick = { showDeleteAllProjectsConfirmation = false; onDeleteAllWorkspaceStorage() }) {
                    Text("Delete all projects", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { showDeleteAllProjectsConfirmation = false }) { Text("Cancel") } }
        )
    }
    if (showDeleteImportedApksConfirmation) {
        AlertDialog(
            onDismissRequest = { showDeleteImportedApksConfirmation = false },
            title = { Text("Delete imported APK library?") },
            text = { Text("This permanently deletes APKs imported into the Apps library. APK files retained inside individual project workspaces remain untouched, so open projects can still be repacked.") },
            confirmButton = {
                TextButton(onClick = { showDeleteImportedApksConfirmation = false; onDeleteImportedApkStorage() }) {
                    Text("Delete APK library", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { showDeleteImportedApksConfirmation = false }) { Text("Cancel") } }
        )
    }
}

@Composable
private fun SettingSwitch(label: String, checked: Boolean, onChange: (Boolean) -> Unit, compact: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = if (compact) 0.dp else 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), style = if (compact) MaterialTheme.typography.bodySmall else MaterialTheme.typography.bodyMedium)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun LogsPage(logs: List<String>, onCopy: () -> Unit, onClear: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Runtime logs", style = MaterialTheme.typography.titleMedium)
                Text("[APP] application · [CORE] OpenGDS.py", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onCopy) { Icon(Icons.Outlined.ContentCopy, "Copy logs") }
            IconButton(onClick = onClear) { Icon(Icons.Outlined.DeleteSweep, "Clear logs") }
        }
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        if (logs.isEmpty()) EmptyState("No log entries", "Application and backend events will appear here.")
        LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            itemsIndexed(logs, key = { index, _ -> "log-entry-$index" }) { _, line ->
                Text(line, Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.surface).padding(9.dp), color = if (line.startsWith("[CORE]")) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.onSurface, fontFamily = FontFamily.Monospace, fontSize = 10.sp, lineHeight = 14.sp)
            }
        }
    }
}
