package com.ABDO10DZ.OpenGDS.core

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.FileOutputStream
import java.io.FilterOutputStream
import java.io.OutputStream
import java.nio.charset.StandardCharsets
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

/** Rebuilds a single APK or a complete split-APK collection, with consistent signing across every part. */
object ApkRepacker {
    private data class ApkPart(
        val source: File,
        val overlay: File,
        val outputName: String
    )

    fun rebuild(
        context: Context,
        workspace: File,
        outputTree: Uri,
        cancelFile: File? = null,
        alwaysUnsigned: Boolean = false,
        signingMode: String = if (alwaysUnsigned) "unsigned" else "local",
        keystoreUri: Uri? = null,
        keystorePassword: String? = null,
        keystoreAlias: String? = null,
        keyPassword: String? = null
    ): List<String> {
        val sourceDir = File(workspace, "source")
        val projectRoot = File(workspace, "project")
        val base = File(sourceDir, "base.apk")
        if (!base.isFile) {
            throw IllegalStateException("Original APK not found. Reopen the imported APK or installed app; folder-only projects export project files, not Android APKs.")
        }
        val label = File(sourceDir, "base.name").takeIf { it.isFile }
            ?.readText(Charsets.UTF_8)?.trim()?.ifBlank { null }
            ?: base.nameWithoutExtension
        val safeStem = safeFileStem(label)
        val splitFiles = sourceDir.listFiles()
            ?.filter { it.isFile && it.name.matches(Regex("split_\\d+\\.apk")) }
            ?.sortedBy { it.name.substringAfter("split_").substringBefore(".").toIntOrNull() ?: Int.MAX_VALUE }
            .orEmpty()

        val parts = buildList {
            add(ApkPart(base, projectRoot, "${safeStem}_repacked.apk"))
            splitFiles.forEach { split ->
                val number = split.name.substringAfter("split_").substringBefore(".")
                val overlay = File(projectRoot, "_splits/split_$number")
                if (!overlay.isDirectory) {
                    throw IllegalStateException("Workspace for ${split.name} is missing; cannot safely rebuild all APK splits.")
                }
                add(ApkPart(split, overlay, "${safeStem}_split_${number}_repacked.apk"))
            }
        }

        val originalSetBytes = parts.sumOf { it.source.length() }
        LogStore.app("Original APK input set: ${parts.size} part(s), ${formatBytes(originalSetBytes)} total (${parts.joinToString { it.source.name }}).")
        if (parts.size > 1) {
            LogStore.app("Detected a split APK set (${parts.size} parts). OpenGDS will create one XAPK bundle with the base and all splits.")
        }

        val destination = DocumentFile.fromTreeUri(context, outputTree)
            ?: throw IllegalStateException("Unable to access the configured APK output folder")
        val tempDir = File(context.cacheDir, "apk-export").apply { mkdirs() }
        val unsignedFiles = mutableListOf<File>()
        val signedFiles = mutableListOf<File>()
        val finalFiles = mutableListOf<File>()

        try {
            // Rebuild and verify every part before attempting to sign any of them.
            parts.forEachIndexed { index, part ->
                checkCancelled(cancelFile)
                val unsigned = File(tempDir, "part_${index}.unsigned.apk")
                val signed = File(tempDir, "part_${index}.signed.apk")
                unsigned.delete()
                signed.delete()
                FileOutputStream(unsigned).use { stream -> writeArchive(part.source, part.overlay, stream, cancelFile) }
                checkCancelled(cancelFile)

                val sourceStats = measureArchive(part.source)
                val outputStats = verifyRebuiltArchive(part.source, part.overlay, unsigned, cancelFile)
                LogStore.app(
                    "APK content audit ${part.source.name}: ${formatBytes(part.source.length())} → ${formatBytes(unsigned.length())}; " +
                        "${sourceStats.entries} source entries / ${outputStats.entries} output entries; " +
                        "uncompressed payload ${formatBytes(sourceStats.uncompressedBytes)} → ${formatBytes(outputStats.uncompressedBytes)}; " +
                        "compressed ZIP payload ${formatBytes(sourceStats.compressedBytes)} → ${formatBytes(outputStats.compressedBytes)}; " +
                        "GDC ${sourceStats.gdcFiles} → ${outputStats.gdcFiles}, PCK ${sourceStats.pckFiles} → ${outputStats.pckFiles}, native libraries ${sourceStats.nativeLibraries} → ${outputStats.nativeLibraries}."
                )
                unsignedFiles += unsigned
                signedFiles += signed
            }

            // Split manifests may omit uses-sdk. Use the base minSdk.
            val signingMinSdk = context.packageManager.getPackageArchiveInfo(
                unsignedFiles.first().absolutePath, 0
            )?.applicationInfo?.minSdkVersion?.takeIf { it > 0 } ?: 1

            LogStore.app("Signing all APK parts for minSdkVersion=$signingMinSdk.")

            // Every part must use the same signing identity.
            var signedAsSet = false
            if (alwaysUnsigned || signingMode == "unsigned") {
                LogStore.app("Unsigned APK output is enabled; all ${parts.size} APK part(s) will remain unsigned.")
            } else {
                try {
                    signedFiles.forEachIndexed { index, signed ->
                        checkCancelled(cancelFile)
                        ApkSigning.sign(
                            unsignedFiles[index], signed, context,
                            mode = signingMode,
                            keystoreUri = keystoreUri,
                            keystorePassword = keystorePassword,
                            keyAlias = keystoreAlias,
                            keyPassword = keyPassword,
                            minSdkVersion = signingMinSdk
                        )
                        LogStore.app("APK signature verified for ${parts[index].source.name}.")
                    }
                    signedAsSet = true
                } catch (signError: Exception) {
                    // A requested signed export must never be reported as successful unsigned output.
                    // Keep the failure visible so the actual key/provider/apksig error can be fixed.
                    signedFiles.forEach { it.delete() }
                    LogStore.app(
                        "APK signing failed in mode '$signingMode'; export aborted. Full details:\n" +
                            signError.stackTraceToString(),
                        signError
                    )
                    throw IllegalStateException(
                        "APK signing failed (${signingMode}): ${signError.message ?: signError.javaClass.simpleName}. " +
                            "No unsigned fallback was created. Open Logs for the full signing trace.",
                        signError
                    )
                }
            }

            parts.indices.forEach { index ->
                finalFiles += if (signedAsSet) signedFiles[index] else unsignedFiles[index]
            }

            val outputFile: File
            val outputName: String
            val mimeType: String
            if (parts.size == 1) {
                outputFile = finalFiles.single()
                outputName = if (signedAsSet) parts.single().outputName
                    else unsignedOutputName(parts.single().outputName)
                mimeType = "application/vnd.android.package-archive"
                if (!signedAsSet) {
                    LogStore.app("Created unsigned APK because unsigned export was explicitly selected: $outputName · sign before installation.")
                }
            } else {
                outputFile = File(tempDir, "${safeStem}_repacked${if (signedAsSet) "" else "_unsigned"}.xapk")
                outputName = outputFile.name
                mimeType = "application/zip"
                writeApkSetArchive(
                    context = context,
                    outputFile = outputFile,
                    parts = parts,
                    apkFiles = finalFiles,
                    signed = signedAsSet,
                    cancelFile = cancelFile
                )
                LogStore.app(
                    "Created ${if (signedAsSet) "signed" else "unsigned"} XAPK bundle: $outputName · " +
                        "${parts.size} APK files inside, preserving ${parts.joinToString { it.source.name }}."
                )
                if (!signedAsSet) LogStore.app("The XAPK contains unsigned APK parts. Sign every inner APK with the same certificate before installation.")
            }

            checkCancelled(cancelFile)
            val existing = destination.findFile(outputName)
            val backupName = "$outputName.opengds-backup-${System.currentTimeMillis()}"
            if (existing != null && !existing.renameTo(backupName)) {
                throw IllegalStateException("Unable to safely replace existing output $outputName; the existing file was kept")
            }
            var created: DocumentFile? = null
            try {
                created = destination.createFile(mimeType, outputName)
                    ?: throw IllegalStateException("Unable to create $outputName in the selected folder")
                val copied = context.contentResolver.openOutputStream(created.uri, "w")?.use { output ->
                    outputFile.inputStream().buffered().use { input ->
                        val buffer = ByteArray(128 * 1024)
                        var bytes = 0L
                        while (true) {
                            checkCancelled(cancelFile)
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                            bytes += count
                        }
                        bytes
                    }
                } ?: throw IllegalStateException("Unable to open output stream for $outputName")
                if (copied != outputFile.length()) throw IllegalStateException("Export size verification failed for $outputName")
                if (existing != null) {
                    val backup = destination.findFile(backupName)
                    if (backup != null && !backup.delete()) {
                        LogStore.app("Export succeeded, but the previous output backup could not be removed: $backupName")
                    }
                }
                LogStore.app("APK export complete: $outputName · ${formatBytes(copied)}${if (parts.size > 1) " · ${parts.size} APK parts bundled" else ""}.")
            } catch (error: Exception) {
                created?.delete()
                if (existing != null) {
                    val backup = destination.findFile(backupName)
                    if (backup != null && !backup.renameTo(outputName)) {
                        throw IllegalStateException("Export failed and the previous output remains stored as $backupName", error)
                    }
                }
                throw error
            }
            return listOf(outputName)
        } finally {
            tempDir.listFiles()?.forEach { it.delete() }
            tempDir.delete()
        }
    }

    /**
     * Writes an XAPK v2 container. It preserves each APK filename and includes the
     * package/split metadata required by XAPK-compatible installers.
     */
    private fun writeApkSetArchive(
        context: Context,
        outputFile: File,
        parts: List<ApkPart>,
        apkFiles: List<File>,
        signed: Boolean,
        cancelFile: File?
    ) {
        if (parts.size < 2 || parts.size != apkFiles.size) {
            throw IllegalArgumentException("A split APK set must contain a base APK and at least one split APK")
        }
        val names = parts.map { it.source.name }
        if (names.distinct().size != names.size || names.first() != "base.apk") {
            throw IllegalStateException("Split APK set has duplicate names or is missing base.apk")
        }

        val digests = apkFiles.map { file -> digestFileAndSha256(file, cancelFile) }
        val pm = context.packageManager
        val flags = android.content.pm.PackageManager.GET_PERMISSIONS
        val baseInfo = pm.getPackageArchiveInfo(apkFiles.first().absolutePath, flags)
            ?: throw IllegalStateException("Cannot read package metadata from rebuilt base.apk")
        val packageName = baseInfo.packageName?.takeIf { it.isNotBlank() }
            ?: throw IllegalStateException("base.apk has no package name")
        val versionCode = baseInfo.longVersionCode
        val appInfo = baseInfo.applicationInfo
            ?: throw IllegalStateException("base.apk has no application metadata")
        appInfo.sourceDir = apkFiles.first().absolutePath
        appInfo.publicSourceDir = apkFiles.first().absolutePath
        val appName = runCatching { appInfo.loadLabel(pm).toString() }
            .getOrNull()?.takeIf { it.isNotBlank() } ?: packageName

        val splitIds = mutableListOf<String>()
        val splitApks = org.json.JSONArray()
            .put(org.json.JSONObject().put("file", names.first()).put("id", "base"))

        parts.drop(1).forEachIndexed { i, part ->
            // Parse split metadata directly. PackageManager can reject
            // individual split APKs when parsed without their base APK.
            val metadata = BinaryAndroidManifest.read(apkFiles[i + 1])

            if (metadata.packageName != packageName) {
                throw IllegalStateException(
                    "${part.source.name} belongs to ${metadata.packageName}, not $packageName"
                )
            }

            if (metadata.versionCode != null &&
                metadata.versionCode != versionCode
            ) {
                throw IllegalStateException(
                    "${part.source.name} version does not match base.apk"
                )
            }

            val id = metadata.splitName
                ?: throw IllegalStateException(
                    "${part.source.name} has no split manifest attribute"
                )

            if (id.isBlank() || id == "base" || id in splitIds) {
                throw IllegalStateException("Invalid or duplicate split ID: $id")
            }

            splitIds += id
            splitApks.put(
                org.json.JSONObject()
                    .put("file", names[i + 1])
                    .put("id", id)
            )
        }

        val manifest = org.json.JSONObject().apply {
            put("xapk_version", 2)
            put("package_name", packageName)
            put("name", appName)
            put("locales_name", org.json.JSONObject().put("en", appName))
            put("version_code", versionCode.toString())
            put("version_name", baseInfo.versionName.orEmpty())

            if (appInfo.minSdkVersion > 0)
                put("min_sdk_version", appInfo.minSdkVersion.toString())
            if (appInfo.targetSdkVersion > 0)
                put("target_sdk_version", appInfo.targetSdkVersion.toString())

            put("permissions", org.json.JSONArray(baseInfo.requestedPermissions?.toList() ?: emptyList<String>()))
            put("total_size", digests.sumOf { it.size })
            put("split_configs", org.json.JSONArray(splitIds))
            put("split_apks", splitApks)
            put("opengds_signed", signed)

            put("opengds_sha256", org.json.JSONArray().apply {
                names.forEachIndexed { i, name ->
                    put(org.json.JSONObject()
                        .put("file", name)
                        .put("sha256", digests[i].sha256)
                        .put("size", digests[i].size))
                }
            })
        }.toString(2)

        outputFile.parentFile?.mkdirs()
        outputFile.delete()
        ZipOutputStream(FileOutputStream(outputFile).buffered()).use { zip ->
            names.forEachIndexed { index, name ->
                checkCancelled(cancelFile)
                val file = apkFiles[index]
                val digest = digests[index]
                zip.putNextEntry(ZipEntry(name).apply {
                    method = ZipEntry.STORED
                    size = digest.size
                    compressedSize = digest.size
                    crc = digest.crc
                })
                file.inputStream().buffered().use { copyCancellable(it, zip, cancelFile) }
                zip.closeEntry()
            }
            zip.putNextEntry(ZipEntry("manifest.json"))
            zip.write(manifest.toByteArray(Charsets.UTF_8))
            zip.closeEntry()
        }

        // Re-open the finished container and verify every embedded APK byte-for-byte.
        ZipFile(outputFile).use { archive ->
            val manifestEntry = archive.getEntry("manifest.json")
                ?: throw IllegalStateException("XAPK export is missing root manifest.json")
            val parsedManifest = archive.getInputStream(manifestEntry).use {
                org.json.JSONObject(String(it.readBytes(), Charsets.UTF_8))
            }
            if (parsedManifest.optInt("xapk_version") != 2 || parsedManifest.optString("package_name").isBlank())
                throw IllegalStateException("XAPK manifest is missing required package metadata")
            if (parsedManifest.optJSONArray("split_apks")?.length() != names.size)
                throw IllegalStateException("XAPK manifest does not list every APK part")
            names.forEachIndexed { index, name ->
                checkCancelled(cancelFile)
                val entry = archive.getEntry(name)
                    ?: throw IllegalStateException("APK set export is missing '$name'")
                val expected = digests[index]
                if (entry.size != expected.size || entry.crc != expected.crc) {
                    throw IllegalStateException("APK set verification failed for '$name'")
                }
                val actual = digestFileAndSha256(archive.getInputStream(entry), cancelFile)
                if (actual != expected) throw IllegalStateException("APK set content verification failed for '$name'")
            }
            if (archive.size() != names.size + 1) {
                throw IllegalStateException("APK set contains unexpected entries; expected ${names.size + 1}, found ${archive.size()}")
            }
        }
        LogStore.app("XAPK integrity verified: ${names.size} original APK filenames, split IDs and manifest preserved; ${formatBytes(outputFile.length())} archive size.")
    }

    private data class FileDigest(val size: Long, val crc: Long, val sha256: String)

    private fun digestFileAndSha256(file: File, cancelFile: File?): FileDigest =
        file.inputStream().buffered().use { digestFileAndSha256(it, cancelFile) }

    private fun digestFileAndSha256(input: java.io.InputStream, cancelFile: File?): FileDigest {
        val crc = CRC32()
        val sha = java.security.MessageDigest.getInstance("SHA-256")
        var size = 0L
        val buffer = ByteArray(128 * 1024)
        input.use { stream ->
            while (true) {
                checkCancelled(cancelFile)
                val count = stream.read(buffer)
                if (count < 0) break
                crc.update(buffer, 0, count)
                sha.update(buffer, 0, count)
                size += count
            }
        }
        val shaHex = sha.digest().joinToString("") { "%02x".format(it) }
        return FileDigest(size, crc.value, shaHex)
    }

    private fun unsignedOutputName(signedName: String): String =
        if (signedName.endsWith(".apk", ignoreCase = true)) {
            signedName.dropLast(4) + "_unsigned.apk"
        } else {
            signedName + "_unsigned.apk"
        }

    private fun checkCancelled(cancelFile: File?) {
        if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
    }

    private fun writeArchive(sourceApk: File, overlayRoot: File, destination: OutputStream, cancelFile: File?) {
        ZipFile(sourceApk).use { source ->
            // Count the exact bytes written so STORED entries receive APK alignment metadata.
            CountingOutputStream(destination).use { counted ->
                ZipOutputStream(counted).use { output ->
                    val written = HashSet<String>()
                    val entries = source.entries()
                    while (entries.hasMoreElements()) {
                        checkCancelled(cancelFile)
                        val entry = entries.nextElement()
                        val name = normalizeEntryName(entry.name) ?: continue
                        // Never drop original APK entries based on workspace naming rules.
                        // Some games legitimately ship files named *.tmp/*.bak or reserved-looking folders.
                        if (entry.isDirectory || isSignatureEntry(name)) continue
                        if (!written.add(name)) continue
                        val overlay = if (isProtectedSourcePath(name)) null
                            else safeChild(overlayRoot, name)?.takeIf { it.isFile }
                        val storedMetadata = if (entry.method == ZipEntry.STORED) {
                            if (overlay != null) storedMetadata(overlay, cancelFile)
                            else StoredMetadata(entry.size, entry.crc)
                        } else null
                        val rewritten = ZipEntry(name).apply {
                            method = entry.method
                            if (entry.time >= 0L) time = entry.time
                            comment = entry.comment
                            if (entry.method == ZipEntry.STORED) {
                                val metadata = storedMetadata
                                    ?: throw IllegalStateException("Missing STORED metadata for $name")
                                size = metadata.size
                                compressedSize = metadata.size
                                crc = metadata.crc
                                extra = alignedExtra(name, entry.extra, counted.count)
                            } else {
                                extra = stripAlignmentExtra(entry.extra)
                            }
                        }
                        output.putNextEntry(rewritten)
                        if (overlay != null) {
                            overlay.inputStream().buffered().use { copyCancellable(it, output, cancelFile) }
                        } else {
                            source.getInputStream(entry).buffered().use { copyCancellable(it, output, cancelFile) }
                        }
                        output.closeEntry()
                    }

                    // Add new compiled GDCs and other runtime resources; exclude editor-only sources.
                    overlayRoot.walkTopDown().filter { it.isFile }.forEach { file ->
                        checkCancelled(cancelFile)
                        val relative = file.relativeTo(overlayRoot).invariantSeparatorsPath
                        val name = normalizeEntryName(relative) ?: return@forEach
                        if (name in written || isSignatureEntry(name) || isWorkspaceOnly(name) || isEditorOnly(name)) return@forEach
                        written += name
                        output.putNextEntry(ZipEntry(name))
                        file.inputStream().buffered().use { copyCancellable(it, output, cancelFile) }
                        output.closeEntry()
                    }
                    checkCancelled(cancelFile)
                    output.finish()
                }
            }
        }
    }

    private data class ArchiveStats(
        val entries: Int,
        val uncompressedBytes: Long,
        val compressedBytes: Long,
        val gdcFiles: Int,
        val pckFiles: Int,
        val nativeLibraries: Int
    )

    private data class EntryDigest(val size: Long, val crc: Long)

    private fun measureArchive(file: File): ArchiveStats = ZipFile(file).use { zip ->
        var entries = 0
        var uncompressed = 0L
        var compressed = 0L
        var gdc = 0
        var pck = 0
        var native = 0
        val all = zip.entries()
        while (all.hasMoreElements()) {
            val entry = all.nextElement()
            if (entry.isDirectory) continue
            entries++
            uncompressed += entry.size.coerceAtLeast(0L)
            compressed += entry.compressedSize.coerceAtLeast(0L)
            val lower = entry.name.lowercase()
            if (lower.endsWith(".gdc")) gdc++
            if (lower.endsWith(".pck")) pck++
            if (lower.startsWith("lib/") && lower.endsWith(".so")) native++
        }
        ArchiveStats(entries, uncompressed, compressed, gdc, pck, native)
    }

    /** Ensures every eligible source entry and every eligible overlay file exists byte-for-byte. */
    private fun verifyRebuiltArchive(
        sourceApk: File,
        overlayRoot: File,
        rebuiltApk: File,
        cancelFile: File?
    ): ArchiveStats {
        val expected = LinkedHashMap<String, EntryDigest>()
        val overlaidGdcPaths = mutableListOf<String>()
        val changedGdcPaths = mutableListOf<String>()
        ZipFile(sourceApk).use { source ->
            val entries = source.entries()
            while (entries.hasMoreElements()) {
                checkCancelled(cancelFile)
                val entry = entries.nextElement()
                val name = normalizeEntryName(entry.name) ?: continue
                if (entry.isDirectory || isSignatureEntry(name) || expected.containsKey(name)) continue
                val overlay = if (isProtectedSourcePath(name)) null
                    else safeChild(overlayRoot, name)?.takeIf { it.isFile }
                val originalDigest = EntryDigest(entry.size, entry.crc)
                val overlayDigest = overlay?.let { digestFile(it, cancelFile) }
                if (overlay != null && name.endsWith(".gdc", ignoreCase = true)) {
                    overlaidGdcPaths += name
                    // Extracted workspaces contain all original GDC assets, not just edited ones.
                    // Distinguish files merely present in the overlay from content actually changed.
                    if (overlayDigest != originalDigest) changedGdcPaths += name
                }
                expected[name] = overlayDigest ?: originalDigest
            }
        }

        overlayRoot.walkTopDown().filter { it.isFile }.forEach { file ->
            checkCancelled(cancelFile)
            val relative = file.relativeTo(overlayRoot).invariantSeparatorsPath
            val name = normalizeEntryName(relative) ?: return@forEach
            if (name in expected || isSignatureEntry(name) || isWorkspaceOnly(name) || isEditorOnly(name)) return@forEach
            expected[name] = digestFile(file, cancelFile)
        }
        if (expected.isEmpty() || "AndroidManifest.xml" !in expected) {
            throw IllegalStateException("Rebuilt APK is missing AndroidManifest.xml or contains no valid archive entries")
        }

        ZipFile(rebuiltApk).use { output ->
            for ((name, digest) in expected) {
                checkCancelled(cancelFile)
                val entry = output.getEntry(name)
                    ?: throw IllegalStateException("APK integrity check failed: missing '$name' after repacking")
                if (entry.size != digest.size || entry.crc != digest.crc) {
                    throw IllegalStateException("APK integrity check failed: size/CRC mismatch for '$name'")
                }
                val actual = output.getInputStream(entry).use { digestStream(it, cancelFile) }
                if (actual != digest) {
                    throw IllegalStateException("APK integrity check failed: damaged content in '$name'")
                }
            }
            val stats = measureArchive(rebuiltApk)
            if (stats.entries < expected.size) {
                throw IllegalStateException("APK integrity check failed: ${expected.size} expected entries but only ${stats.entries} were written")
            }
            if (overlaidGdcPaths.isNotEmpty()) {
                LogStore.app(
                    "Direct GDSC APK overlay verified: ${overlaidGdcPaths.size} existing .gdc path(s) present in the workspace overlay; " +
                        "${changedGdcPaths.size} payload(s) differ from the original APK (size/CRC), including " +
                        (changedGdcPaths.take(8).joinToString().ifBlank { "none" }) +
                        (if (changedGdcPaths.size > 8) " and ${changedGdcPaths.size - 8} more." else ".")
                )
            }
            return stats
        }
    }

    private fun digestFile(file: File, cancelFile: File?): EntryDigest =
        file.inputStream().buffered().use { digestStream(it, cancelFile) }

    private fun digestStream(input: java.io.InputStream, cancelFile: File?): EntryDigest {
        val crc = CRC32()
        var size = 0L
        val buffer = ByteArray(128 * 1024)
        while (true) {
            checkCancelled(cancelFile)
            val count = input.read(buffer)
            if (count < 0) break
            crc.update(buffer, 0, count)
            size += count
        }
        return EntryDigest(size, crc.value)
    }

    private data class StoredMetadata(val size: Long, val crc: Long)

    private fun copyCancellable(input: java.io.InputStream, output: OutputStream, cancelFile: File?) {
        val buffer = ByteArray(128 * 1024)
        while (true) {
            checkCancelled(cancelFile)
            val count = input.read(buffer)
            if (count < 0) break
            output.write(buffer, 0, count)
        }
    }

    private fun storedMetadata(file: File, cancelFile: File?): StoredMetadata {
        val crc = CRC32()
        var size = 0L
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(128 * 1024)
            while (true) {
                checkCancelled(cancelFile)
                val count = input.read(buffer)
                if (count < 0) break
                crc.update(buffer, 0, count)
                size += count
            }
        }
        return StoredMetadata(size, crc.value)
    }

    /**
     * Android APK alignment extra field (0xD935). Native libraries are aligned to
     * 16 KiB for modern Android page sizes; other uncompressed entries are 4-byte aligned.
     */
    private fun alignedExtra(name: String, original: ByteArray?, localHeaderOffset: Long): ByteArray {
        val clean = stripAlignmentExtra(original) ?: ByteArray(0)
        val filenameBytes = name.toByteArray(StandardCharsets.UTF_8).size.toLong()
        val alignment = if (name.startsWith("lib/") && name.endsWith(".so", ignoreCase = true)) 16 * 1024 else 4
        val dataStartWithoutAlignment = localHeaderOffset + 30L + filenameBytes + clean.size
        val padding = ((alignment - ((dataStartWithoutAlignment + 6L) % alignment)) % alignment).toInt()
        val payloadLength = 2 + padding
        val alignmentField = ByteArray(4 + payloadLength)
        alignmentField[0] = 0x35
        alignmentField[1] = 0xD9.toByte()
        alignmentField[2] = (payloadLength and 0xff).toByte()
        alignmentField[3] = ((payloadLength ushr 8) and 0xff).toByte()
        alignmentField[4] = (alignment and 0xff).toByte()
        alignmentField[5] = ((alignment ushr 8) and 0xff).toByte()
        return clean + alignmentField
    }

    /** Removes stale alignment records before calculating a new local-header layout. */
    private fun stripAlignmentExtra(extra: ByteArray?): ByteArray? {
        if (extra == null || extra.isEmpty()) return extra
        val output = java.io.ByteArrayOutputStream(extra.size)
        var offset = 0
        while (offset + 4 <= extra.size) {
            val id = (extra[offset].toInt() and 0xff) or ((extra[offset + 1].toInt() and 0xff) shl 8)
            val size = (extra[offset + 2].toInt() and 0xff) or ((extra[offset + 3].toInt() and 0xff) shl 8)
            val end = offset + 4 + size
            if (end > extra.size) {
                output.write(extra, offset, extra.size - offset)
                return output.toByteArray()
            }
            if (id != 0xD935) output.write(extra, offset, end - offset)
            offset = end
        }
        if (offset < extra.size) output.write(extra, offset, extra.size - offset)
        return output.toByteArray().takeIf { it.isNotEmpty() }
    }

    private class CountingOutputStream(output: OutputStream) : FilterOutputStream(output) {
        var count: Long = 0
            private set

        override fun write(value: Int) {
            out.write(value)
            count++
        }

        override fun write(buffer: ByteArray, offset: Int, length: Int) {
            out.write(buffer, offset, length)
            count += length
        }
    }

    private fun safeChild(root: File, relative: String): File? = try {
        val rootPath = root.canonicalFile.toPath()
        val child = File(root, relative).canonicalFile
        if (child.toPath().startsWith(rootPath)) child else null
    } catch (_: Exception) { null }

    private fun normalizeEntryName(raw: String): String? {
        val name = raw.replace('\\', '/')
        if (name.isBlank() || name.startsWith('/') || name.contains('\u0000')) return null
        if (name.split('/').any { it.isBlank() || it == "." || it == ".." }) return null
        return name
    }

    private fun isSignatureEntry(name: String): Boolean {
        val upper = name.uppercase()
        if (!upper.startsWith("META-INF/")) return false
        val leaf = upper.substringAfterLast('/')
        return leaf == "MANIFEST.MF" || leaf.endsWith(".SF") || leaf.endsWith(".RSA") ||
            leaf.endsWith(".DSA") || leaf.endsWith(".EC") || leaf.startsWith("SIG-")
    }

    /** Paths that are used by OpenGDS to stage split APKs or PCK metadata, never APK overlays. */
    private fun isProtectedSourcePath(name: String): Boolean =
        name.startsWith("_splits/", ignoreCase = true) || name.equals(".opengds_pck_map", ignoreCase = true)

    private fun isWorkspaceOnly(name: String): Boolean {
        val lower = name.lowercase()
        if (lower.startsWith("_pck/") || lower.startsWith("_splits/")) return true
        if (lower == ".opengds_pck_map") return true
        return lower.endsWith(".bak") || lower.endsWith(".replacement") ||
            lower.endsWith(".copying") || lower.endsWith(".opengds-tmp") || lower.endsWith(".tmp")
    }

    private fun isEditorOnly(name: String): Boolean {
        val lower = name.lowercase()
        return lower.endsWith(".gd") || lower.endsWith(".smali")
    }

    private fun safeFileStem(value: String): String = value
        .substringAfterLast('/')
        .replace(Regex("(?i)\\.apk$"), "")
        .replace(Regex("[^A-Za-z0-9._-]"), "_")
        .trim('_', '.', '-')
        .take(96)
        .ifBlank { "app" }
}
