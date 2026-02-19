package com.example.gemmaapp

import android.content.Context
import android.widget.Toast
import com.google.mediapipe.tasks.text.textembedder.TextEmbedder
import io.objectbox.Box
import kotlin.concurrent.thread
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Syncs photos/audio from ESP32 SD card to app database.
 * ESP32 IP is static (192.168.4.1 when phone connects to ESP32_CAM WiFi).
 */
object Esp32SyncHelper {

    private const val ESP32_BASE_URL = "http://192.168.4.1"

    fun sync(
        context: Context,
        embedder: TextEmbedder?,
        box: Box<Knowledge>?,
        onComplete: (newCount: Int, message: String) -> Unit
    ) {
        if (box == null) {
            onComplete(0, "Database not available")
            return
        }
        if (embedder == null) {
            onComplete(0, "Embedder not ready")
            return
        }

        (context.applicationContext as? GemmaApp)?.pauseBleForSync()

        thread {
            try {
                val baseUrl = ESP32_BASE_URL
                val files = fetchFileList(baseUrl)
                var newCount = 0
                val imagesDir = File(context.filesDir, "knowledge_images").apply { mkdirs() }
                val audioDir = File(context.filesDir, "knowledge_audio").apply { mkdirs() }

                val indexMap = mutableMapOf<String, String>()
                if (files.contains("index.txt")) {
                    downloadFile(baseUrl, "index.txt")?.split("\n")?.forEach { line ->
                        val trimmed = line.trim()
                        if (trimmed.contains(",") || trimmed.contains("\t")) {
                            val parts = trimmed.split(Regex("[,\t]"), limit = 2)
                            if (parts.size >= 2) indexMap[parts[0].trim()] = parts[1].trim()
                        }
                    }
                }

                val allRecords = box.query().build().find()
                val filenameRe = Regex("\"filename\"\\s*:\\s*\"([^\"]+)\"")
                val audioFilenameRe = Regex("\"audioFilename\"\\s*:\\s*\"([^\"]+)\"")

                val existingFilenames = allRecords.flatMap { r ->
                    val meta = r.metadata ?: ""
                    listOfNotNull(
                        filenameRe.find(meta)?.groupValues?.get(1),
                        audioFilenameRe.find(meta)?.groupValues?.get(1)
                    )
                }.toSet()

                val transcriber = AudioTranscriber(context)

                for (filename in files) {
                    if (filename == "index.txt") continue
                    if (filename in existingFilenames) continue
                    if (!isImageFile(filename)) continue

                    val destFile = File(imagesDir, "esp32_${System.currentTimeMillis()}_$filename")
                    val bytes = downloadFileBytes(baseUrl, filename) ?: continue
                    FileOutputStream(destFile).use { it.write(bytes) }

                    val contentFromIndex = indexMap[filename]
                    val datetime = extractDatetimeFromFilename(filename)
                    val metadata = if (datetime != null) {
                        """{"source":"esp32","filename":"$filename","type":"image","datetime":"$datetime"}"""
                    } else {
                        """{"source":"esp32","filename":"$filename","type":"image"}"""
                    }
                    val vector = if (contentFromIndex != null && contentFromIndex.isNotEmpty()) {
                        embedder.embed(contentFromIndex).embeddingResult().embeddings().first().floatEmbedding()
                    } else null

                    box.put(Knowledge(
                        content = contentFromIndex,
                        imagePath = destFile.absolutePath,
                        audioPath = null,
                        metadata = metadata,
                        vector = vector
                    ))
                    newCount++
                }

                val indexToImageRecord = box.query().build().find()
                    .filter { it.imagePath != null }
                    .mapNotNull { r ->
                        val meta = r.metadata ?: ""
                        val imgFilename = filenameRe.find(meta)?.groupValues?.get(1)
                            ?: r.imagePath?.substringAfterLast('/') ?: return@mapNotNull null
                        extractIndexFromFilename(imgFilename)?.let { idx -> idx to r }
                    }
                    .groupBy { it.first }
                    .mapValues { it.value.first().second }

                for (filename in files) {
                    if (filename == "index.txt") continue
                    if (filename in existingFilenames) continue
                    if (!isAudioFile(filename)) continue

                    val destFile = File(audioDir, "esp32_${System.currentTimeMillis()}_$filename")
                    val bytes = downloadFileBytes(baseUrl, filename) ?: continue
                    FileOutputStream(destFile).use { it.write(bytes) }

                    val idx = extractIndexFromFilename(filename) ?: continue
                    val imageRecord = indexToImageRecord[idx] ?: continue
                    if (imageRecord.metadata?.contains("audioFilename") == true) continue

                    val transcript = if (filename.endsWith(".wav", true)) {
                        transcriber.ensureModel()
                        transcriber.transcribe(destFile)
                    } else null
                    val contextStr = when {
                        transcript == null -> null
                        transcript.isEmpty() -> "No speech"
                        else -> transcript
                    }
                    val vector = if (contextStr != null) {
                        embedder.embed(contextStr).embeddingResult().embeddings().first().floatEmbedding()
                    } else imageRecord.vector

                    val meta = imageRecord.metadata ?: "{}"
                    var newMeta = if (meta.contains("audioFilename")) meta else meta.dropLast(1) + ",\"audioFilename\":\"$filename\"}"
                    if (!newMeta.contains("\"datetime\"")) {
                        extractDatetimeFromFilename(filename)?.let { dt ->
                            newMeta = newMeta.dropLast(1) + ",\"datetime\":\"$dt\"}"
                        }
                    }

                    imageRecord.content = contextStr ?: imageRecord.content
                    imageRecord.audioPath = destFile.absolutePath
                    imageRecord.vector = vector
                    imageRecord.metadata = newMeta
                    box.put(imageRecord)
                    newCount++
                }

                for (r in box.query().build().find()) {
                    val meta = r.metadata ?: continue
                    if (meta.contains("\"datetime\"")) continue
                    val toTry = filenameRe.find(meta)?.groupValues?.get(1)
                        ?: audioFilenameRe.find(meta)?.groupValues?.get(1)
                        ?: r.imagePath?.substringAfterLast('/')?.let { it.substringAfter("esp32_").substringAfter("_") }
                        ?: continue
                    extractDatetimeFromFilename(toTry)?.let { dt ->
                        r.metadata = meta.dropLast(1) + ",\"datetime\":\"$dt\"}"
                        box.put(r)
                    }
                }

                notifyEsp32SyncComplete(baseUrl)
                val msg = if (newCount > 0) "Synced: $newCount new memories" else "No new files"
                onComplete(newCount, msg)
            } catch (e: Exception) {
                e.printStackTrace()
                notifyEsp32SyncComplete(ESP32_BASE_URL)
                onComplete(0, "Sync failed: ${e.message}")
            } finally {
                (context.applicationContext as? GemmaApp)?.resumeBleAfterSync()
            }
        }
    }

    private fun notifyEsp32SyncComplete(baseUrl: String) {
        val fullUrl = baseUrl.trimEnd('/') + "/sync-complete"
        repeat(3) {
            try {
                val conn = URL(fullUrl).openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                conn.connectTimeout = 5000
                conn.readTimeout = 5000
                conn.inputStream.use { it.readBytes() }
                return
            } catch (_: Exception) { }
            Thread.sleep(500)
        }
    }

    private fun fetchFileList(baseUrl: String): List<String> {
        val base = baseUrl.trimEnd('/')
        val url = URL("$base/list")
        repeat(3) { attempt ->
            try {
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                conn.connectTimeout = 10000   // 10s - fail quickly when device not connected
                conn.readTimeout = 30000
                return conn.inputStream.use { stream ->
                    val json = stream.bufferedReader().readText().trim()
                    when {
                        json.startsWith("[") -> parseJsonArray(JSONArray(json))
                        json.startsWith("{") -> {
                            val obj = JSONObject(json)
                            when {
                                obj.has("files") -> parseJsonArray(obj.getJSONArray("files"))
                                obj.has("list") -> parseJsonArray(obj.getJSONArray("list"))
                                else -> emptyList()
                            }
                        }
                        else -> emptyList()
                    }
                }
            } catch (e: Exception) {
                if (attempt == 2) throw e
                Thread.sleep(1000)
            }
        }
        return emptyList()
    }

    private fun parseJsonArray(arr: JSONArray): List<String> {
        return (0 until arr.length()).mapNotNull { i ->
            try {
                when (val item = arr.get(i)) {
                    is String -> item.trim().removePrefix("/")
                    is JSONObject -> item.optString("name", item.optString("filename", item.optString("file"))).trim().removePrefix("/")
                    else -> null
                }
            } catch (_: Exception) { null }
        }.filter { it.isNotEmpty() }
    }

    private fun downloadFile(baseUrl: String, filename: String): String? {
        val bytes = downloadFileBytes(baseUrl, filename) ?: return null
        return bytes.toString(Charsets.UTF_8)
    }

    private fun downloadFileBytes(baseUrl: String, filename: String): ByteArray? {
        val base = baseUrl.trimEnd('/')
        val url = URL("$base/download?file=${java.net.URLEncoder.encode(filename, "UTF-8")}")
        repeat(3) { attempt ->
            try {
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                conn.connectTimeout = 60000
                conn.readTimeout = 300000
                return conn.inputStream.readBytes()
            } catch (e: Exception) {
                if (attempt == 2) return null
                Thread.sleep(1500)
            }
        }
        return null
    }

    private fun extractIndexFromFilename(filename: String): String? {
        val datetimeRe = Regex("(\\d{8}_\\d{6})\\.[^.]+$")
        datetimeRe.find(filename)?.groupValues?.get(1)?.let { return it }
        val num = Regex("(\\d+)\\.[^.]+$").find(filename)?.groupValues?.get(1) ?: return null
        return num.trimStart('0').ifEmpty { "0" }
    }

    private fun extractDatetimeFromFilename(filename: String): String? {
        val clean = filename.trim().removePrefix("/")
        val datetimeRe = Regex("(\\d{8})_(\\d{6})\\.[^.]+$")
        val m = datetimeRe.find(clean) ?: return null
        val (datePart, timePart) = m.destructured
        val year = datePart.take(4)
        val month = datePart.drop(4).take(2)
        val day = datePart.drop(6)
        val hour = timePart.take(2)
        val min = timePart.drop(2).take(2)
        val sec = timePart.drop(4)
        return "$year-$month-$day $hour:$min:$sec"
    }

    private fun isImageFile(name: String): Boolean {
        val ext = name.substringAfterLast('.', "").lowercase()
        return ext in listOf("jpg", "jpeg", "png", "gif", "webp", "bmp")
    }

    private fun isAudioFile(name: String): Boolean {
        val ext = name.substringAfterLast('.', "").lowercase()
        return ext in listOf("wav", "mp3", "m4a", "ogg", "webm", "flac")
    }
}
