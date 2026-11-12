package com.ABDO10DZ.OpenGDS.core

import java.io.File
import java.io.RandomAccessFile
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64

/**
 * Reads and rebuilds ordinary Godot PCK v2-v4 archives.
 * APK exports commonly store project resources in assets/<name>.pck.
 * Encrypted directories, encrypted entries, sparse bundles and delta entries are
 * deliberately skipped; a partial extraction is never offered for rebuilding.
 */
object GodotPckExtractor {
    private const val FLAG_DIRECTORY_ENCRYPTED = 1L shl 0
    private const val FLAG_RELATIVE_FILE_BASE = 1L shl 1
    private const val FLAG_SPARSE_BUNDLE = 1L shl 2
    private const val ENTRY_ENCRYPTED = 1L shl 0
    private const val ENTRY_REMOVAL = 1L shl 1
    private const val ENTRY_DELTA = 1L shl 2
    private const val MAX_ENTRIES = 100_000L
    private const val MAX_ENTRY_BYTES = 512L * 1024 * 1024
    private const val MAX_TOTAL_BYTES = 2L * 1024 * 1024 * 1024
    private const val MAX_PATH_BYTES = 4096L
    private const val ALIGNMENT = 32L
    private const val MAP_FILE = ".opengds_pck_map"

    private data class Entry(
        val path: String,
        val offset: Long,
        val size: Long,
        val md5: ByteArray,
        val flags: Long
    )

    private data class Mapping(
        val sourceRelativePath: String,
        val contentRelativePath: String,
        val formatVersion: Int,
        val engineMajor: Int,
        val engineMinor: Int,
        val enginePatch: Int,
        val sourceDigest: String,
        val canRebuild: Boolean
    )

    private data class WriteEntry(
        val file: File,
        val path: String,
        val bytes: Long,
        val digest: ByteArray,
        var offset: Long = 0L
    )

    data class Result(
        val extracted: Int,
        val skipped: Int,
        val godotScripts: Int,
        val message: String
    )

    fun extractPacks(projectRoot: File, cancelFile: File? = null): List<Result> {
        if (!projectRoot.isDirectory) return emptyList()
        val packs = projectRoot.walkTopDown()
            .filter { file ->
                file.isFile && file.extension.equals("pck", true) &&
                    !file.relativeTo(projectRoot).invariantSeparatorsPath.startsWith("_pck/")
            }
            .toList()
        if (packs.isEmpty()) return emptyList()

        val mappings = readMappings(projectRoot)
        val results = packs.mapIndexed { index, pack ->
            checkCancelled(cancelFile)
            val sourceRelative = pack.relativeTo(projectRoot).invariantSeparatorsPath
            val digest = pack.md5(cancelFile).toHex()
            val previous = mappings.firstOrNull { it.sourceRelativePath == sourceRelative }
            var staging: File? = null
            try {
                if (previous != null && previous.sourceDigest == digest &&
                    File(projectRoot, previous.contentRelativePath).isDirectory) {
                    return@mapIndexed Result(0, 0, 0, "[PCK] ${pack.name}: extraction is current; existing workspace edits preserved.")
                }
                val safeBase = pack.nameWithoutExtension.replace(Regex("[^A-Za-z0-9._-]"), "_")
                    .take(48).ifBlank { "pack" }
                var uniqueIndex = index + 1
                var candidateRelative = "_pck/${safeBase}_$uniqueIndex"
                while (previous == null && (mappings.any { it.contentRelativePath == candidateRelative } || File(projectRoot, candidateRelative).exists())) {
                    uniqueIndex++
                    candidateRelative = "_pck/${safeBase}_$uniqueIndex"
                }
                val output = File(projectRoot, previous?.contentRelativePath ?: candidateRelative)
                output.parentFile?.mkdirs()
                val stage = File(output.parentFile, output.name + ".importing")
                val backup = File(output.parentFile, output.name + ".previous")
                staging = stage
                if (stage.exists() && !stage.deleteRecursively()) throw IllegalStateException("Unable to clear temporary PCK extraction folder")
                val result = extractOne(pack, stage, cancelFile)
                checkCancelled(cancelFile)

                backup.deleteRecursively()
                val hadPrevious = output.exists()
                if (hadPrevious && !output.renameTo(backup)) {
                    throw IllegalStateException("Unable to preserve the previous extracted PCK folder")
                }
                if (!stage.renameTo(output)) {
                    if (hadPrevious) backup.renameTo(output)
                    throw IllegalStateException("Unable to activate the completed PCK extraction")
                }

                val mapping = Mapping(
                    sourceRelativePath = sourceRelative,
                    contentRelativePath = output.relativeTo(projectRoot).invariantSeparatorsPath,
                    formatVersion = result.second.formatVersion,
                    engineMajor = result.second.engineMajor,
                    engineMinor = result.second.engineMinor,
                    enginePatch = result.second.enginePatch,
                    sourceDigest = digest,
                    canRebuild = result.second.canRebuild
                )
                mappings.removeAll { it.sourceRelativePath == mapping.sourceRelativePath }
                mappings += mapping
                try {
                    writeMappings(projectRoot, mappings)
                } catch (error: Exception) {
                    output.deleteRecursively()
                    if (hadPrevious && backup.exists()) backup.renameTo(output)
                    throw error
                }
                if (backup.exists()) backup.deleteRecursively()
                result.first
            } catch (error: Exception) {
                staging?.deleteRecursively()
                if (isCancelled(error, cancelFile)) throw error
                mappings.removeAll { it.sourceRelativePath == sourceRelative }
                runCatching { writeMappings(projectRoot, mappings) }
                Result(0, 0, 0, "[PCK] ${pack.relativeTo(projectRoot)}: ${error.message ?: "unsupported PCK"}; rebuild disabled")
            }
        }
        checkCancelled(cancelFile)
        writeMappings(projectRoot, mappings)
        return results
    }

    fun canRebuild(projectRoot: File, selectedFile: File): Boolean {
        val selectedRelative = relativePathOrNull(projectRoot, selectedFile) ?: return false
        return readMappings(projectRoot).any { mapping ->
            mapping.canRebuild && selectedRelative.startsWith(mapping.contentRelativePath.trimEnd('/') + "/")
        }
    }

    /** Rebuilds only the PCK that owns [selectedFile], retaining its PCK and engine versions. */
    fun rebuildForFile(projectRoot: File, selectedFile: File, cancelFile: File? = null): String {
        val selectedRelative = relativePathOrNull(projectRoot, selectedFile)
            ?: throw IllegalArgumentException("Selected file is outside the project workspace")
        val mapping = readMappings(projectRoot).firstOrNull { item ->
            selectedRelative.startsWith(item.contentRelativePath.trimEnd('/') + "/")
        } ?: throw IllegalStateException("Selected file is not inside an extracted PCK")
        return rebuildMapping(projectRoot, mapping, cancelFile)
    }

    /** Rebuild every fully extracted PCK before APK export. Partial/unsupported packs abort safely. */
    fun rebuildAll(projectRoot: File, cancelFile: File? = null): List<String> {
        val packFiles = projectRoot.walkTopDown()
            .filter { file ->
                file.isFile && file.extension.equals("pck", true) &&
                    !file.relativeTo(projectRoot).invariantSeparatorsPath.startsWith("_pck/")
            }
            .toList()
        val mappings = readMappings(projectRoot)
        val mappedPaths = mappings.mapTo(HashSet()) { it.sourceRelativePath }
        val unmapped = packFiles.filter { it.relativeTo(projectRoot).invariantSeparatorsPath !in mappedPaths }
        if (unmapped.isNotEmpty()) {
            val names = unmapped.take(3).joinToString { it.relativeTo(projectRoot).invariantSeparatorsPath }
            throw IllegalStateException("Could not validate/extract every PCK (${names}). Reopen the APK and check the PCK extraction log before repacking.")
        }
        if (mappings.any { !it.canRebuild }) {
            throw IllegalStateException("At least one embedded PCK was only partially extracted; safe APK repacking is unavailable for this workspace.")
        }
        if (mappings.size != packFiles.size) {
            throw IllegalStateException("PCK mapping does not match the APK workspace. Reopen the original APK before repacking.")
        }
        return mappings.map { mapping ->
            checkCancelled(cancelFile)
            rebuildMapping(projectRoot, mapping, cancelFile)
        }
    }

    private fun rebuildMapping(projectRoot: File, mapping: Mapping, cancelFile: File?): String {
        checkCancelled(cancelFile)
        if (!mapping.canRebuild) {
            throw IllegalStateException("This PCK was only partially extracted; encrypted, delta, or invalid entries prevent a safe rebuild")
        }
        val contentRoot = File(projectRoot, mapping.contentRelativePath).canonicalFile
        val target = File(projectRoot, mapping.sourceRelativePath).canonicalFile
        if (!contentRoot.isDirectory || !target.isFile || !target.parentFile.isDirectory) throw IllegalStateException("PCK workspace files are missing; reopen the original APK before rebuilding")
        val temp = File(target.parentFile, target.name + ".opengds-tmp")
        val backup = File(target.parentFile, target.name + ".bak")
        temp.delete()

        writePack(
            contentRoot, temp, mapping.formatVersion,
            mapping.engineMajor, mapping.engineMinor, mapping.enginePatch, cancelFile
        )
        checkCancelled(cancelFile)
        backup.delete()
        var previousMoved = false
        var rebuiltMoved = false
        try {
            if (target.exists()) {
                if (!target.renameTo(backup)) throw IllegalStateException("Unable to back up the original ${target.name}")
                previousMoved = true
            }
            if (!temp.renameTo(target)) throw IllegalStateException("Unable to replace ${target.name}; original PCK was restored")
            rebuiltMoved = true
            checkCancelled(cancelFile)
            val updated = mapping.copy(sourceDigest = target.md5(cancelFile).toHex())
            val mappings = readMappings(projectRoot)
            mappings.removeAll { it.sourceRelativePath == mapping.sourceRelativePath }
            mappings += updated
            writeMappings(projectRoot, mappings)
            return "Rebuilt ${mapping.sourceRelativePath} from ${mapping.contentRelativePath}; original saved as ${backup.name}"
        } catch (error: Exception) {
            if (rebuiltMoved) target.delete()
            if (previousMoved && backup.exists() && !backup.renameTo(target)) {
                throw IllegalStateException("PCK rebuild failed and the original remains at ${backup.absolutePath}", error)
            }
            temp.delete()
            throw error
        }
    }

    private data class ParsedPck(
        val entries: List<Entry>,
        val fileBase: Long,
        val formatVersion: Int,
        val engineMajor: Int,
        val engineMinor: Int,
        val enginePatch: Int
    )

    private fun extractOne(pck: File, outputRoot: File, cancelFile: File?): Pair<Result, MappingData> {
        RandomAccessFile(pck, "r").use { input ->
            val parsed = parse(input, cancelFile)
            outputRoot.mkdirs()
            var extracted = 0
            var skipped = 0
            var scripts = 0
            var totalBytes = 0L
            val seenPaths = HashSet<String>()
            val dataEnd = input.length()
            val outputCanonical = outputRoot.canonicalFile.toPath()

            for (entry in parsed.entries) {
                checkCancelled(cancelFile)
                if ((entry.flags and (ENTRY_ENCRYPTED or ENTRY_REMOVAL or ENTRY_DELTA)) != 0L) {
                    skipped++
                    continue
                }
                if (entry.size > MAX_ENTRY_BYTES || entry.size > MAX_TOTAL_BYTES - totalBytes) {
                    skipped++
                    continue
                }
                val normalized = entry.path.removePrefix("res://").replace('\\', '/')
                val segments = normalized.split('/')
                if (normalized.isBlank() || normalized.startsWith('/') || normalized.contains('\u0000') || segments.any { it == ".." || it.isBlank() } || !seenPaths.add(normalized)) {
                    skipped++
                    continue
                }
                val absoluteOffset = try { Math.addExact(parsed.fileBase, entry.offset) } catch (_: ArithmeticException) { skipped++; continue }
                if (absoluteOffset < 0L || entry.size < 0L || absoluteOffset > dataEnd || entry.size > dataEnd - absoluteOffset) {
                    skipped++
                    continue
                }

                val destination = File(outputRoot, normalized)
                val destinationPath = destination.canonicalFile.toPath()
                if (!destinationPath.startsWith(outputCanonical)) {
                    skipped++
                    continue
                }
                destination.parentFile?.mkdirs()
                val temporary = File(destination.parentFile, destination.name + ".pcktmp")
                try {
                    val digest = MessageDigest.getInstance("MD5")
                    input.seek(absoluteOffset)
                    temporary.outputStream().buffered().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var remaining = entry.size
                        while (remaining > 0L) {
                            checkCancelled(cancelFile)
                            val count = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                            if (count <= 0) throw IllegalArgumentException("unexpected end of PCK data for ${entry.path}")
                            digest.update(buffer, 0, count)
                            output.write(buffer, 0, count)
                            remaining -= count
                        }
                    }
                    if (!MessageDigest.isEqual(digest.digest(), entry.md5)) {
                        temporary.delete()
                        skipped++
                        continue
                    }
                    if (destination.exists() && !destination.delete()) throw IllegalStateException("cannot replace ${entry.path}")
                    if (!temporary.renameTo(destination)) throw IllegalStateException("cannot commit ${entry.path}")
                    totalBytes += entry.size
                    extracted++
                    if (destination.extension.equals("gdc", true)) scripts++
                } catch (error: Exception) {
                    temporary.delete()
                    throw error
                }
            }

            val canRebuild = skipped == 0
            val mapping = MappingData(
                parsed.formatVersion, parsed.engineMajor, parsed.engineMinor, parsed.enginePatch, canRebuild
            )
            val result = Result(
                extracted,
                skipped,
                scripts,
                "[PCK] ${pck.name}: extracted $extracted entries ($scripts .gdc files); skipped $skipped encrypted, invalid, or oversized entries to ${outputRoot.name}/" +
                    if (canRebuild) " Rebuild enabled." else " Rebuild disabled to avoid dropping skipped entries."
            )
            return result to mapping
        }
    }

    private data class MappingData(
        val formatVersion: Int,
        val engineMajor: Int,
        val engineMinor: Int,
        val enginePatch: Int,
        val canRebuild: Boolean
    )

    private fun parse(input: RandomAccessFile, cancelFile: File?): ParsedPck {
        checkCancelled(cancelFile)
        if (input.length() < 96L) throw IllegalArgumentException("PCK header is truncated")
        val magic = ByteArray(4).also(input::readFully)
        if (!magic.contentEquals(byteArrayOf(0x47, 0x44, 0x50, 0x43))) {
            throw IllegalArgumentException("missing GDPC PCK signature")
        }

        val version = input.readU32()
        if (version !in 2L..4L) throw IllegalArgumentException("PCK format version $version is not supported (supported: 2–4)")
        val engineMajor = input.readU32().toInt()
        val engineMinor = input.readU32().toInt()
        val enginePatch = input.readU32().toInt()
        val packFlags = input.readU32()
        if ((packFlags and FLAG_DIRECTORY_ENCRYPTED) != 0L) {
            throw IllegalArgumentException("PCK directory is encrypted; a project encryption key is required")
        }
        if ((packFlags and FLAG_SPARSE_BUNDLE) != 0L) {
            throw IllegalArgumentException("sparse PCK bundles reference external payload files and are not supported")
        }

        // The PCK has already been carved out of the APK ZIP, so its header offset is zero.
        val fileBase = input.readU64()
        val directoryPosition = if (version >= 3L) input.readU64() else {
            input.skipFully(16L * 4L)
            input.filePointer
        }
        if (directoryPosition < 0L || directoryPosition > input.length() - 4L) {
            throw IllegalArgumentException("PCK directory offset is outside the archive")
        }
        input.seek(directoryPosition)
        val entryCount = input.readU32()
        if (entryCount > MAX_ENTRIES) throw IllegalArgumentException("PCK directory has too many entries: $entryCount")

        val entries = ArrayList<Entry>(entryCount.toInt())
        repeat(entryCount.toInt()) {
            checkCancelled(cancelFile)
            val pathLength = input.readU32()
            if (pathLength <= 0L || pathLength > MAX_PATH_BYTES || pathLength > input.length() - input.filePointer) {
                throw IllegalArgumentException("invalid PCK path length: $pathLength")
            }
            val pathBytes = ByteArray(pathLength.toInt()).also(input::readFully)
            val path = String(pathBytes, StandardCharsets.UTF_8).trimEnd('\u0000')
            val offset = input.readU64()
            val size = input.readU64()
            val md5 = ByteArray(16).also(input::readFully)
            val flags = input.readU32()
            entries += Entry(path, offset, size, md5, flags)
        }
        return ParsedPck(entries, fileBase, version.toInt(), engineMajor, engineMinor, enginePatch)
    }

    private fun writePack(
        contentRoot: File,
        destination: File,
        version: Int,
        engineMajor: Int,
        engineMinor: Int,
        enginePatch: Int,
        cancelFile: File?
    ) {
        val files = contentRoot.walkTopDown()
            .filter { it.isFile && !it.name.endsWith(".pcktmp") && !it.name.endsWith(".opengds-tmp") }
            .sortedBy { it.relativeTo(contentRoot).invariantSeparatorsPath }
            .toList()
        if (files.size > MAX_ENTRIES) throw IllegalStateException("PCK has more than $MAX_ENTRIES files")

        val entries = ArrayList<WriteEntry>(files.size)
        var total = 0L
        for (file in files) {
            checkCancelled(cancelFile)
            val relative = file.relativeTo(contentRoot).invariantSeparatorsPath
            if (relative.isBlank() || relative.startsWith('/') || relative.split('/').any { it == ".." || it.isBlank() }) {
                throw IllegalArgumentException("unsafe PCK project path: $relative")
            }
            if (relative.toByteArray(StandardCharsets.UTF_8).size > MAX_PATH_BYTES) {
                throw IllegalArgumentException("PCK path exceeds $MAX_PATH_BYTES bytes: $relative")
            }
            val size = file.length()
            if (size > MAX_ENTRY_BYTES || size > MAX_TOTAL_BYTES - total) {
                throw IllegalStateException("PCK rebuild exceeds the 512 MiB/file or 2 GiB/total safety limit")
            }
            total += size
            entries += WriteEntry(file, relative, size, file.md5(cancelFile))
        }

        destination.parentFile?.mkdirs()
        RandomAccessFile(destination, "rw").use { output ->
            output.setLength(0L)
            if (version == 2) {
                val directorySize = directorySize(entries.map { it.path })
                val fileBase = align(96L + directorySize, ALIGNMENT)
                var offset = 0L
                entries.forEach { entry ->
                    checkCancelled(cancelFile)
                    entry.offset = offset
                    offset = align(Math.addExact(offset, entry.bytes), ALIGNMENT)
                }
                output.writeAscii("GDPC")
                output.writeU32(2)
                output.writeU32(engineMajor.toLong())
                output.writeU32(engineMinor.toLong())
                output.writeU32(enginePatch.toLong())
                output.writeU32(FLAG_RELATIVE_FILE_BASE)
                output.writeU64(fileBase)
                repeat(16) { output.writeU32(0) }
                writeDirectory(output, entries)
                output.padTo(fileBase)
                entries.forEach { entry ->
                    checkCancelled(cancelFile)
                    output.writeFile(entry.file, cancelFile)
                    output.padTo(align(output.filePointer - fileBase, ALIGNMENT) + fileBase)
                }
            } else {
                output.writeAscii("GDPC")
                output.writeU32(version.toLong())
                output.writeU32(engineMajor.toLong())
                output.writeU32(engineMinor.toLong())
                output.writeU32(enginePatch.toLong())
                output.writeU32(FLAG_RELATIVE_FILE_BASE)
                output.writeU64(0L) // file base patched after the header is written
                output.writeU64(0L) // directory offset patched after file data
                repeat(16) { output.writeU32(0) }
                output.padTo(align(output.filePointer, ALIGNMENT))
                val fileBase = output.filePointer
                var offset = 0L
                entries.forEach { entry ->
                    checkCancelled(cancelFile)
                    entry.offset = offset
                    output.writeFile(entry.file, cancelFile)
                    offset = align(Math.addExact(offset, entry.bytes), ALIGNMENT)
                    output.padTo(fileBase + offset)
                }
                val directoryOffset = output.filePointer
                writeDirectory(output, entries)
                val endPosition = output.filePointer
                output.seek(24L)
                output.writeU64(fileBase)
                output.writeU64(directoryOffset)
                output.seek(endPosition)
            }
            output.fd.sync()
        }
    }

    private fun directorySize(paths: List<String>): Long {
        var size = 4L
        paths.forEach { path ->
            val paddedPathLength = align(path.toByteArray(StandardCharsets.UTF_8).size.toLong(), 4L)
            size = Math.addExact(size, 4L + paddedPathLength + 8L + 8L + 16L + 4L)
        }
        return size
    }

    private fun writeDirectory(output: RandomAccessFile, entries: List<WriteEntry>) {
        output.writeU32(entries.size.toLong())
        entries.forEach { entry ->
            val encoded = entry.path.toByteArray(StandardCharsets.UTF_8)
            val paddedLength = align(encoded.size.toLong(), 4L)
            output.writeU32(paddedLength)
            output.write(encoded)
            repeat((paddedLength - encoded.size).toInt()) { output.write(0) }
            output.writeU64(entry.offset)
            output.writeU64(entry.bytes)
            output.write(entry.digest)
            output.writeU32(0L)
        }
    }

    private fun readMappings(projectRoot: File): MutableList<Mapping> {
        val mapFile = File(projectRoot.parentFile, MAP_FILE)
        if (!mapFile.isFile) return mutableListOf()
        return mapFile.readLines(Charsets.UTF_8).mapNotNull { line ->
            val fields = line.split('\t')
            if (fields.size != 8) return@mapNotNull null
            try {
                Mapping(
                    decodeField(fields[0]), decodeField(fields[1]), fields[2].toInt(),
                    fields[3].toInt(), fields[4].toInt(), fields[5].toInt(),
                    fields[6], fields[7] == "1"
                )
            } catch (_: Exception) { null }
        }.toMutableList()
    }

    private fun writeMappings(projectRoot: File, mappings: List<Mapping>) {
        val mapFile = File(projectRoot.parentFile, MAP_FILE)
        val temporary = File(mapFile.parentFile, mapFile.name + ".tmp")
        val text = mappings.joinToString("\n") { mapping ->
            listOf(
                encodeField(mapping.sourceRelativePath), encodeField(mapping.contentRelativePath),
                mapping.formatVersion.toString(), mapping.engineMajor.toString(),
                mapping.engineMinor.toString(), mapping.enginePatch.toString(),
                mapping.sourceDigest, if (mapping.canRebuild) "1" else "0"
            ).joinToString("\t")
        }
        temporary.writeText(text, Charsets.UTF_8)
        val backup = File(mapFile.parentFile, mapFile.name + ".bak")
        backup.delete()
        if (mapFile.exists() && !mapFile.renameTo(backup)) {
            temporary.delete()
            throw IllegalStateException("Unable to preserve the existing PCK workspace map")
        }
        if (!temporary.renameTo(mapFile)) {
            if (backup.exists()) backup.renameTo(mapFile)
            temporary.delete()
            throw IllegalStateException("Unable to write PCK workspace map; previous map restored")
        }
        backup.delete()
    }

    private fun encodeField(value: String): String = Base64.getUrlEncoder().withoutPadding()
        .encodeToString(value.toByteArray(StandardCharsets.UTF_8))

    private fun decodeField(value: String): String = String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8)

    private fun relativePathOrNull(root: File, child: File): String? = try {
        val rootPath = root.canonicalFile.toPath()
        val childPath = child.canonicalFile.toPath()
        if (!childPath.startsWith(rootPath)) null else root.canonicalFile.toPath().relativize(childPath).toString().replace(File.separatorChar, '/')
    } catch (_: Exception) { null }

    private fun align(value: Long, alignment: Long): Long = ((value + alignment - 1L) / alignment) * alignment

    private fun RandomAccessFile.writeAscii(value: String) = write(value.toByteArray(StandardCharsets.US_ASCII))

    private fun RandomAccessFile.writeU32(value: Long) {
        if (value < 0L || value > 0xffff_ffffL) throw IllegalArgumentException("32-bit PCK field out of range")
        write((value and 0xff).toInt())
        write(((value ushr 8) and 0xff).toInt())
        write(((value ushr 16) and 0xff).toInt())
        write(((value ushr 24) and 0xff).toInt())
    }

    private fun RandomAccessFile.writeU64(value: Long) {
        if (value < 0L) throw IllegalArgumentException("negative PCK offset")
        writeU32(value and 0xffff_ffffL)
        writeU32((value ushr 32) and 0xffff_ffffL)
    }

    private fun RandomAccessFile.writeFile(file: File, cancelFile: File?) {
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                checkCancelled(cancelFile)
                val count = input.read(buffer)
                if (count < 0) break
                write(buffer, 0, count)
            }
        }
    }

    private fun RandomAccessFile.padTo(target: Long) {
        if (target < filePointer) throw IllegalArgumentException("PCK alignment moved backwards")
        while (filePointer < target) write(0)
    }

    private fun RandomAccessFile.readU32(): Long {
        val b0 = readUnsignedByte().toLong()
        val b1 = readUnsignedByte().toLong()
        val b2 = readUnsignedByte().toLong()
        val b3 = readUnsignedByte().toLong()
        return b0 or (b1 shl 8) or (b2 shl 16) or (b3 shl 24)
    }

    private fun RandomAccessFile.readU64(): Long {
        val low = readU32()
        val high = readU32()
        if (high > 0x7fff_ffffL) throw IllegalArgumentException("PCK offset exceeds supported file size")
        return (high shl 32) or low
    }

    private fun RandomAccessFile.skipFully(byteCount: Long) {
        val target = Math.addExact(filePointer, byteCount)
        if (target > length()) throw IllegalArgumentException("truncated PCK reserved header")
        seek(target)
    }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

    private fun checkCancelled(cancelFile: File?) {
        if (cancelFile?.exists() == true) throw IllegalStateException("Operation cancelled by user")
    }

    private fun isCancelled(error: Exception, cancelFile: File?): Boolean =
        cancelFile?.exists() == true || error.message?.contains("cancelled", ignoreCase = true) == true

    private fun File.md5(cancelFile: File? = null): ByteArray {
        val digest = MessageDigest.getInstance("MD5")
        inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                checkCancelled(cancelFile)
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest()
    }
}
