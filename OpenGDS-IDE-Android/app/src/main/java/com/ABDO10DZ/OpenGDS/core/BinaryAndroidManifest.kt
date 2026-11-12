package com.ABDO10DZ.OpenGDS.core

import java.io.File
import java.nio.charset.Charset
import java.util.zip.ZipFile

internal data class BinaryApkManifest(
    val packageName: String,
    val splitName: String?,
    val versionCode: Long?
)

internal object BinaryAndroidManifest {
    private const val STRING_POOL = 0x0001
    private const val XML_TYPE = 0x0003
    private const val START_ELEMENT = 0x0102
    private const val UTF8_FLAG = 0x100

    fun read(apk: File): BinaryApkManifest {
        val data = ZipFile(apk).use { zip ->
            val entry = zip.getEntry("AndroidManifest.xml")
                ?: error("${apk.name} has no AndroidManifest.xml")
            zip.getInputStream(entry).use { it.readBytes() }
        }

        require(data.size >= 8 && u16(data, 0) == XML_TYPE) {
            "${apk.name}: invalid binary AndroidManifest.xml"
        }

        var strings = emptyList<String>()
        var offset = u16(data, 2)
        var packageName: String? = null
        var splitName: String? = null
        var versionCode: Long? = null
        var versionMajor = 0L

        while (offset + 8 <= data.size) {
            val type = u16(data, offset)
            val header = u16(data, offset + 2)
            val size = u32(data, offset + 4).toInt()

            require(size >= 8 && offset + size <= data.size && header >= 8) {
                "Malformed binary XML in ${apk.name}"
            }

            if (type == STRING_POOL) {
                strings = readPool(data, offset, header, size)
            } else if (type == START_ELEMENT && strings.isNotEmpty()) {
                if (str(strings, u32(data, offset + 20)) == "manifest") {
                    val attrStart = u16(data, offset + 24)
                    val attrSize = u16(data, offset + 26)
                    val count = u16(data, offset + 28)

                    require(attrSize >= 20) { "Invalid manifest attribute size" }

                    val first = offset + 16 + attrStart

                    repeat(count) { i ->
                        val a = first + i * attrSize
                        require(a + 20 <= offset + size) {
                            "Truncated manifest attribute"
                        }

                        val name = str(strings, u32(data, a + 4))
                            ?: return@repeat
                        val raw = u32(data, a + 8)
                        val valueType = data[a + 15].toInt() and 255
                        val valueData = u32(data, a + 16)

                        val value = when {
                            raw != 0xffffffffL -> str(strings, raw)
                            valueType == 3 -> str(strings, valueData)
                            else -> null
                        }

                        when (name) {
                            "package" -> packageName = value
                            "split" -> splitName = value
                            "versionCode" ->
                                if (valueType in 0x10..0x12) versionCode = valueData
                            "versionCodeMajor" ->
                                if (valueType in 0x10..0x12) versionMajor = valueData
                        }
                    }
                    break
                }
            }
            offset += size
        }

        val pkg = packageName?.takeIf { it.isNotBlank() }
            ?: error("Package name missing in ${apk.name}")

        val fullVersion = versionCode?.let {
            (versionMajor shl 32) or (it and 0xffffffffL)
        }

        return BinaryApkManifest(
            pkg, splitName?.takeIf { it.isNotBlank() }, fullVersion
        )
    }

    private fun readPool(
        d: ByteArray, offset: Int, header: Int, size: Int
    ): List<String> {
        require(header >= 28) { "Invalid string pool" }

        val count = u32(d, offset + 8).toInt()
        val flags = u32(d, offset + 16).toInt()
        val stringsStart = u32(d, offset + 20).toInt()

        require(count in 0..200000 &&
            offset + header + count * 4 <= offset + size) {
            "Invalid string pool offsets"
        }

        return List(count) { i ->
            val relative = u32(d, offset + header + i * 4).toInt()
            val start = offset + stringsStart + relative

            require(start >= offset && start < offset + size) {
                "Invalid string offset"
            }

            if (flags and UTF8_FLAG != 0) {
                val chars = len8(d, start)
                val bytes = len8(d, start + chars.second)
                val at = start + chars.second + bytes.second

                require(bytes.first >= 0 && at + bytes.first <= offset + size)
                String(d, at, bytes.first, Charsets.UTF_8)
            } else {
                val length = len16(d, start)
                val at = start + length.second
                val byteCount = length.first * 2

                require(byteCount >= 0 && at + byteCount <= offset + size)
                String(d, at, byteCount, Charset.forName("UTF-16LE"))
            }
        }
    }

    private fun len8(d: ByteArray, p: Int): Pair<Int, Int> {
        val a = d[p].toInt() and 255
        return if (a and 128 == 0) a to 1
        else (((a and 127) shl 8) or (d[p + 1].toInt() and 255)) to 2
    }

    private fun len16(d: ByteArray, p: Int): Pair<Int, Int> {
        val a = u16(d, p)
        return if (a and 0x8000 == 0) a to 2
        else (((a and 0x7fff) shl 16) or u16(d, p + 2)) to 4
    }

    private fun str(s: List<String>, i: Long): String? =
        if (i == 0xffffffffL || i < 0 || i >= s.size) null
        else s[i.toInt()]

    private fun u16(d: ByteArray, p: Int): Int =
        (d[p].toInt() and 255) or
        ((d[p + 1].toInt() and 255) shl 8)

    private fun u32(d: ByteArray, p: Int): Long =
        (d[p].toLong() and 255) or
        ((d[p + 1].toLong() and 255) shl 8) or
        ((d[p + 2].toLong() and 255) shl 16) or
        ((d[p + 3].toLong() and 255) shl 24)
}
