package com.ABDO10DZ.OpenGDS.core

import org.jf.baksmali.Baksmali
import org.jf.baksmali.BaksmaliOptions
import org.jf.dexlib2.DexFileFactory
import org.jf.dexlib2.Opcodes
import org.jf.smali.Smali
import org.jf.smali.SmaliOptions
import java.io.File

/** Local DEX <-> Smali toolchain. No shell process or network connection is used. */
object SmaliToolchain {
    private val dexName = Regex("classes(?:[2-9]|[1-9][0-9]+)?\\.dex", RegexOption.IGNORE_CASE)

    fun disassemble(projectRoot: File, overwrite: Boolean): List<String> {
        val results = mutableListOf<String>()
        val dexFiles = projectRoot.walkTopDown()
            .filter { it.isFile && dexName.matches(it.name) && it.path.split(File.separator).none { p -> p == "smali" } }
            .toList()
        if (dexFiles.isEmpty()) throw IllegalStateException("No classes.dex files found in this project")

        dexFiles.forEach { dex ->
            val output = File(File(dex.parentFile, "smali"), dex.nameWithoutExtension)
            if (output.exists() && !overwrite) {
                results += "[SKIP] ${dex.relativeTo(projectRoot)}: Smali directory already exists"
                return@forEach
            }
            val temp = File(output.parentFile, output.name + ".opengds-tmp").apply {
                deleteRecursively()
                mkdirs()
            }
            try {
                val dexFile = DexFileFactory.loadDexFile(dex, Opcodes.forApi(36))
                val options = BaksmaliOptions().apply {
                    apiLevel = 36
                    debugInfo = true
                    parameterRegisters = true
                }
                val done = Baksmali.disassembleDexFile(
                    dexFile,
                    temp,
                    Runtime.getRuntime().availableProcessors().coerceIn(1, 4),
                    options
                )
                if (!done) throw IllegalStateException("baksmali reported one or more disassembly errors")
                if (output.exists()) {
                    val backup = File(output.parentFile, output.name + ".bak")
                    backup.deleteRecursively()
                    if (!output.renameTo(backup)) throw IllegalStateException("Unable to back up existing ${output.name}")
                }
                if (!temp.renameTo(output)) throw IllegalStateException("Unable to commit Smali output")
                results += "[OK] ${dex.relativeTo(projectRoot)} -> ${output.relativeTo(projectRoot)}"
            } catch (error: Exception) {
                temp.deleteRecursively()
                results += "[ERROR] ${dex.relativeTo(projectRoot)}: ${error.message}"
                throw IllegalStateException(results.joinToString("\n"), error)
            }
        }
        return results
    }

    fun assemble(projectRoot: File, overwrite: Boolean): List<String> {
        val results = mutableListOf<String>()
        val smaliDirs = projectRoot.walkTopDown()
            .filter { it.isDirectory && it.parentFile?.name == "smali" && it.name.matches(Regex("classes(?:[2-9]|[1-9][0-9]+)?")) }
            .toList()
        if (smaliDirs.isEmpty()) throw IllegalStateException("No generated Smali source directories found")

        smaliDirs.forEach { directory ->
            val dex = File(directory.parentFile?.parentFile, directory.name + ".dex")
            if (dex.exists() && !overwrite) {
                results += "[SKIP] ${dex.relativeTo(projectRoot)} already exists"
                return@forEach
            }
            val temp = File(dex.parentFile, dex.name + ".opengds-tmp")
            try {
                val options = SmaliOptions().apply {
                    apiLevel = 36
                    jobs = Runtime.getRuntime().availableProcessors().coerceIn(1, 4)
                    outputDexFile = temp.absolutePath
                }
                val done = Smali.assemble(options, directory.absolutePath)
                if (!done || !temp.isFile) throw IllegalStateException("smali assembly failed")
                if (dex.exists()) {
                    val backup = File(dex.parentFile, dex.name + ".bak")
                    backup.delete()
                    if (!dex.renameTo(backup)) throw IllegalStateException("Unable to back up ${dex.name}")
                }
                if (!temp.renameTo(dex)) throw IllegalStateException("Unable to replace ${dex.name}")
                results += "[OK] ${directory.relativeTo(projectRoot)} -> ${dex.relativeTo(projectRoot)}"
            } catch (error: Exception) {
                temp.delete()
                results += "[ERROR] ${directory.relativeTo(projectRoot)}: ${error.message}"
                throw IllegalStateException(results.joinToString("\n"), error)
            }
        }
        return results
    }
}
