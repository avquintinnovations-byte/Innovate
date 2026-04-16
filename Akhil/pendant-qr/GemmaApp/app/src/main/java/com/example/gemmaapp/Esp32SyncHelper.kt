package com.example.gemmaapp

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
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
 *
 * Uses ConnectivityManager.requestNetwork() + WiFiLock to prevent Android from
 * dropping the ESP32_CAM AP (no-internet Wi-Fi) during or after sync.
 */
object Esp32SyncHelper {

    private const val ESP32_BASE_URL = "http://192.168.4.1"
    private const val ESP32_SSID = "ESP32_CAM"
    private const val ESP32_PASS = "12345678"

    // Hold the network callback so Android keeps the Wi-Fi network alive
    private var activeNetworkCallback: ConnectivityManager.NetworkCallback? = null
    private var activeCm: ConnectivityManager? = null
    private var activeNetwork: Network? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private val callbackHandler = Handler(Looper.getMainLooper())
    private var keepAliveRunnable: Runnable? = null
    private var savedAppContext: android.content.Context? = null

    /**
     * Keep the current Wi-Fi connection alive for the whole app session.
     *
     * Call this from UI lifecycle (e.g. Activity.onResume()) after the user manually
     * connects to ESP32_CAM in Wi-Fi settings. This prevents Android from dropping
     * the connection to a no-internet AP.
     */
    fun holdWifiIfConnected(context: Context) {
        acquireNetwork(context)
        startKeepAlive()
    }

    /** Call this once from sync thread to bind to the current Wi-Fi network robustly */
    @Synchronized
    private fun acquireNetwork(context: Context): Network? {
        val appCtx = context.applicationContext
        savedAppContext = appCtx
        val cm = appCtx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        activeCm = cm

        // On API 29+: add a WifiNetworkSuggestion so Android knows ESP32_CAM is a
        // trusted network. This prevents Android from marking it as "bad" and disabling
        // it after a connectivity check fails or after the user ignores the "no internet" dialog.
        // CHANGE_WIFI_STATE permission is already in the manifest; no new runtime permission needed.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            addEsp32NetworkSuggestion(appCtx)
        }

        // Check if already on Wi-Fi
        val current = cm.activeNetwork
        val caps = current?.let { cm.getNetworkCapabilities(it) }
        if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
            // Bind process AND hold the network via requestNetwork
            cm.bindProcessToNetwork(current)
            activeNetwork = current
            acquireWifiLock(appCtx)
            holdNetworkViaRequest(appCtx, cm)
            return current
        }
        return null
    }

    /**
     * Register ESP32_CAM as a trusted Wi-Fi suggestion (API 29+, needs CHANGE_WIFI_STATE only).
     *
     * This tells Android:
     *  - The app intentionally uses this network — do NOT disable/block it.
     *  - Auto-connect when in range and no internet network is competing.
     *
     * Without this, Android can permanently disable ESP32_CAM after detecting "no internet",
     * making manual reconnection fail silently.
     */
    @Suppress("DEPRECATION")
    private fun addEsp32NetworkSuggestion(ctx: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        try {
            val wm = ctx.getSystemService(Context.WIFI_SERVICE) as WifiManager
            val suggestion = android.net.wifi.WifiNetworkSuggestion.Builder()
                .setSsid(ESP32_SSID)
                .setWpa2Passphrase(ESP32_PASS)
                .setIsAppInteractionRequired(false)
                .build()
            // Remove stale suggestions first (ignore errors)
            try { wm.removeNetworkSuggestions(emptyList()) } catch (_: Exception) { }
            wm.addNetworkSuggestions(listOf(suggestion))
        } catch (_: Exception) { }
    }

    private fun acquireWifiLock(ctx: Context) {
        val wifi = ctx.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val lock = wifi.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "GemmaApp:Esp32Sync")
        lock.setReferenceCounted(false)
        if (!lock.isHeld) lock.acquire()
        wifiLock = lock
    }

    /** Register a NetworkRequest so Android OS doesn't tear down the Wi-Fi */
    private fun holdNetworkViaRequest(ctx: Context, cm: ConnectivityManager) {
        // Unregister any existing callback first
        activeNetworkCallback?.let {
            try { cm.unregisterNetworkCallback(it) } catch (_: Exception) { }
        }

        // IMPORTANT: ESP32_CAM has NO internet. If we require INTERNET capability (default),
        // Android may immediately drop or de-prioritize the network after sync.
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                // Update process binding whenever a Wi-Fi network becomes available
                cm.bindProcessToNetwork(network)
                activeNetwork = network
            }
            override fun onLost(network: Network) {
                if (network == activeNetwork) {
                    activeNetwork = null
                    // Android dropped the connection. Schedule a fresh requestNetwork() call.
                    // Re-registering the request is the most reliable cross-version way to
                    // trigger Android to search for and reconnect to a matching Wi-Fi network.
                    callbackHandler.postDelayed({
                        synchronized(this@Esp32SyncHelper) {
                            val ctx = savedAppContext ?: return@synchronized
                            val savedCm = activeCm ?: return@synchronized
                            holdNetworkViaRequest(ctx, savedCm)
                        }
                        // Nudge for older Android versions
                        try {
                            val wm = savedAppContext?.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                            wm?.reconnect()
                        } catch (_: Exception) { }
                    }, 1500)
                }
            }
        }
        activeNetworkCallback = cb
        try {
            cm.requestNetwork(request, cb, callbackHandler)
        } catch (_: Exception) { }
    }

    @Synchronized
    private fun startKeepAlive() {
        if (keepAliveRunnable != null) return
        keepAliveRunnable = object : Runnable {
            override fun run() {
                try {
                    val net = activeNetwork
                    if (net != null) {
                        // Light keep-alive ping so Android considers the Wi-Fi "in use".
                        val conn = openConnection(URL(ESP32_BASE_URL.trimEnd('/') + "/status"), net)
                        conn.requestMethod = "GET"
                        conn.connectTimeout = 1500
                        conn.readTimeout = 1500
                        try {
                            conn.inputStream.use { it.readBytes() }
                        } finally {
                            try { conn.disconnect() } catch (_: Exception) { }
                        }
                    } else {
                        // Network lost — try to reconnect to ESP32_CAM.
                        try {
                            val wm = savedAppContext?.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                            wm?.reconnect()
                        } catch (_: Exception) { }
                    }
                } catch (_: Exception) {
                    // Connection failed — try reconnect so we recover without user action.
                    try {
                        val wm = savedAppContext?.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                        wm?.reconnect()
                    } catch (_: Exception) { }
                } finally {
                    // keep pinging as long as app process is alive
                    callbackHandler.postDelayed(this, 5000)
                }
            }
        }
        callbackHandler.post(keepAliveRunnable!!)
    }

    @Synchronized
    private fun stopKeepAlive() {
        keepAliveRunnable?.let { callbackHandler.removeCallbacks(it) }
        keepAliveRunnable = null
    }

    @Synchronized
    fun releaseNetwork() {
        stopKeepAlive()
        try {
            activeCm?.bindProcessToNetwork(null)
        } catch (_: Exception) { }
        try {
            activeNetworkCallback?.let { activeCm?.unregisterNetworkCallback(it) }
        } catch (_: Exception) { }
        try {
            if (wifiLock?.isHeld == true) wifiLock?.release()
        } catch (_: Exception) { }
        activeNetworkCallback = null
        activeNetwork = null
        activeCm = null
        wifiLock = null
        savedAppContext = null
    }

    fun sync(
        context: Context,
        embedder: TextEmbedder?,
        box: Box<Knowledge>?,
        onComplete: (newCount: Int, message: String) -> Unit,
        onFilesFound: ((count: Int) -> Unit)? = null,
        onMemoryReady: ((record: Knowledge) -> Unit)? = null
    ) {
        if (box == null) { onComplete(0, "Database not available"); return }
        if (embedder == null) { onComplete(0, "Embedder not ready"); return }

        (context.applicationContext as? GemmaApp)?.pauseBleForSync()

        thread {
            val network = acquireNetwork(context)
            val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

            try {
                val baseUrl = ESP32_BASE_URL
                val files = fetchFileList(baseUrl, network)
                var newCount = 0
                val imagesDir = File(context.filesDir, "knowledge_images").apply { mkdirs() }
                val audioDir  = File(context.filesDir, "knowledge_audio").apply { mkdirs() }

                val indexMap = mutableMapOf<String, String>()
                if (files.contains("index.txt")) {
                    downloadFile(baseUrl, "index.txt", network)?.split("\n")?.forEach { line ->
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

                // Report new image count upfront so UI can show placeholders immediately
                val newImageFiles = files.filter { it != "index.txt" && it !in existingFilenames && isImageFile(it) }
                // Map timestamp index → audio filename for quick pairing
                val audioByIndex: Map<String, String> = files
                    .filter { isAudioFile(it) }
                    .mapNotNull { f -> extractIndexFromFilename(f)?.let { it to f } }
                    .toMap()

                if (onFilesFound != null && newImageFiles.isNotEmpty()) {
                    mainHandler.post { onFilesFound(newImageFiles.size) }
                }

                // Download each image then its paired audio immediately — avoids the second-pass
                // stall where audio downloads fail after a long image-only download run.
                for (imageFilename in newImageFiles) {
                    val imageFile = File(imagesDir, "esp32_${System.currentTimeMillis()}_$imageFilename")
                    val imageBytes = downloadFileBytes(baseUrl, imageFilename, network) ?: continue
                    FileOutputStream(imageFile).use { it.write(imageBytes) }

                    val caption  = indexMap[imageFilename]
                    val datetime = extractDatetimeFromFilename(imageFilename)
                    val idx      = extractIndexFromFilename(imageFilename)

                    val audioFilename = idx?.let { audioByIndex[it] }?.takeIf { it !in existingFilenames }

                    var audioPath:    String?     = null
                    var finalContent: String?     = caption
                    var finalVector:  FloatArray? = if (!caption.isNullOrEmpty())
                        embedder.embed(caption).embeddingResult().embeddings().first().floatEmbedding()
                    else null

                    if (audioFilename != null) {
                        try {
                            val audioBytes = downloadFileBytes(baseUrl, audioFilename, network)
                            if (audioBytes != null) {
                                val audioFile = File(audioDir, "esp32_${System.currentTimeMillis()}_$audioFilename")
                                FileOutputStream(audioFile).use { it.write(audioBytes) }
                                audioPath = audioFile.absolutePath

                                val transcript = if (audioFilename.endsWith(".wav", true)) {
                                    transcriber.ensureModel()
                                    transcriber.transcribe(audioFile)
                                } else null
                                if (!transcript.isNullOrEmpty()) {
                                    finalContent = transcript
                                    finalVector  = embedder.embed(transcript).embeddingResult().embeddings().first().floatEmbedding()
                                }
                            }
                        } catch (e: Exception) {
                            audioPath = null  // save image only; retroactive pass below will retry
                        }
                    }

                    val metadata = buildString {
                        append("""{"source":"esp32","filename":"$imageFilename","type":"image"""")
                        if (datetime != null) append(""","datetime":"$datetime"""")
                        if (audioFilename != null && audioPath != null) append(""","audioFilename":"$audioFilename"""")
                        append("}")
                    }

                    val record = Knowledge(
                        content   = finalContent,
                        imagePath = imageFile.absolutePath,
                        audioPath = audioPath,
                        metadata  = metadata,
                        vector    = finalVector
                    )
                    box.put(record)
                    newCount++
                    if (onMemoryReady != null) mainHandler.post { onMemoryReady(record) }
                }

                // Retroactive pass: image records from a previous sync still missing audio
                val retroRecords = box.query().build().find().filter { r ->
                    r.imagePath != null &&
                    r.audioPath == null &&
                    r.metadata?.contains("audioFilename") != true
                }.mapNotNull { r ->
                    val meta  = r.metadata ?: return@mapNotNull null
                    val imgF  = filenameRe.find(meta)?.groupValues?.get(1) ?: return@mapNotNull null
                    val imgIdx = extractIndexFromFilename(imgF) ?: return@mapNotNull null
                    val audioF = audioByIndex[imgIdx]?.takeIf { it !in existingFilenames } ?: return@mapNotNull null
                    r to audioF
                }

                for ((record, audioFilename) in retroRecords) {
                    try {
                        val audioBytes = downloadFileBytes(baseUrl, audioFilename, network) ?: continue
                        val audioFile  = File(audioDir, "esp32_${System.currentTimeMillis()}_$audioFilename")
                        FileOutputStream(audioFile).use { it.write(audioBytes) }

                        val transcript = if (audioFilename.endsWith(".wav", true)) {
                            transcriber.ensureModel()
                            transcriber.transcribe(audioFile)
                        } else null
                        val contextStr = transcript?.takeIf { it.isNotEmpty() }

                        record.audioPath = audioFile.absolutePath
                        val meta = record.metadata ?: "{}"
                        record.metadata = meta.dropLast(1) + ""","audioFilename":"$audioFilename"}"""
                        if (contextStr != null) {
                            record.content = contextStr
                            record.vector  = embedder.embed(contextStr).embeddingResult().embeddings().first().floatEmbedding()
                        }
                        box.put(record)
                        newCount++
                    } catch (e: Exception) {
                        // Skip this audio file; it can be retried on the next sync
                    }
                }

                for (r in box.query().build().find()) {
                    val meta = r.metadata ?: continue
                    if (meta.contains("\"datetime\"")) continue
                    val toTry = filenameRe.find(meta)?.groupValues?.get(1)
                        ?: audioFilenameRe.find(meta)?.groupValues?.get(1)
                        ?: r.imagePath?.substringAfterLast('/')
                            ?.let { it.substringAfter("esp32_").substringAfter("_") }
                        ?: continue
                    extractDatetimeFromFilename(toTry)?.let { dt ->
                        r.metadata = meta.dropLast(1) + ",\"datetime\":\"$dt\"}"
                        box.put(r)
                    }
                }

                notifyEsp32SyncComplete(baseUrl, network)
                val msg = if (newCount > 0) "Synced: $newCount new memories" else "No new files"
                onComplete(newCount, msg)

            } catch (e: Exception) {
                e.printStackTrace()
                notifyEsp32SyncComplete(ESP32_BASE_URL, network)
                onComplete(0, "Sync failed: ${e.message}")
            } finally {
                // Keep network hold alive (don't release) so Android doesn't drop ESP32_CAM.
                // Network is only released when the user starts a new sync or the app restarts.
                (context.applicationContext as? GemmaApp)?.resumeBleAfterSync()
            }
        }
    }

    private fun notifyEsp32SyncComplete(baseUrl: String, network: Network?) {
        val fullUrl = baseUrl.trimEnd('/') + "/sync-complete"
        repeat(3) {
            try {
                val conn = openConnection(URL(fullUrl), network)
                conn.requestMethod = "GET"
                conn.connectTimeout = 5000
                conn.readTimeout = 5000
                try {
                    conn.inputStream.use { it.readBytes() }
                } finally {
                    try { conn.disconnect() } catch (_: Exception) { }
                }
                return
            } catch (_: Exception) { }
            try { Thread.sleep(500) } catch (_: Exception) { }
        }
    }

    private fun fetchFileList(baseUrl: String, network: Network?): List<String> {
        val url = URL("${baseUrl.trimEnd('/')}/list")
        repeat(3) { attempt ->
            try {
                val conn = openConnection(url, network)
                conn.requestMethod = "GET"
                conn.connectTimeout = 10000
                conn.readTimeout = 30000
                try {
                    return conn.inputStream.use { stream ->
                        val json = stream.bufferedReader().readText().trim()
                        when {
                            json.startsWith("[") -> parseJsonArray(JSONArray(json))
                            json.startsWith("{") -> {
                                val obj = JSONObject(json)
                                when {
                                    obj.has("files") -> parseJsonArray(obj.getJSONArray("files"))
                                    obj.has("list")  -> parseJsonArray(obj.getJSONArray("list"))
                                    else             -> emptyList()
                                }
                            }
                            else -> emptyList()
                        }
                    }
                } finally {
                    try { conn.disconnect() } catch (_: Exception) { }
                }
            } catch (e: Exception) {
                if (attempt == 2) throw e
                try { Thread.sleep(1000) } catch (_: Exception) { }
            }
        }
        return emptyList()
    }

    private fun parseJsonArray(arr: JSONArray): List<String> =
        (0 until arr.length()).mapNotNull { i ->
            try {
                when (val item = arr.get(i)) {
                    is String    -> item.trim().removePrefix("/")
                    is JSONObject -> item.optString("name",
                                        item.optString("filename",
                                            item.optString("file"))).trim().removePrefix("/")
                    else -> null
                }
            } catch (_: Exception) { null }
        }.filter { it.isNotEmpty() }

    private fun downloadFile(baseUrl: String, filename: String, network: Network?): String? {
        val bytes = downloadFileBytes(baseUrl, filename, network) ?: return null
        return bytes.toString(Charsets.UTF_8)
    }

    private fun downloadFileBytes(baseUrl: String, filename: String, network: Network?): ByteArray? {
        val url = URL("${baseUrl.trimEnd('/')}/download?file=${java.net.URLEncoder.encode(filename, "UTF-8")}")
        repeat(3) { attempt ->
            try {
                val conn = openConnection(url, network)
                conn.requestMethod = "GET"
                conn.connectTimeout = 60000
                conn.readTimeout   = 300000
                try {
                    return conn.inputStream.readBytes()
                } finally {
                    try { conn.disconnect() } catch (_: Exception) { }
                }
            } catch (e: Exception) {
                if (attempt == 2) return null
                try { Thread.sleep(1500) } catch (_: Exception) { }
            }
        }
        return null
    }

    /**
     * Open an HTTP connection through the specific Wi-Fi Network object if available.
     * This is the critical piece: using network.openConnection() bypasses Android's
     * default routing and ensures traffic goes through ESP32_CAM even if Android
     * "switches" to a different default network.
     */
    private fun openConnection(url: URL, network: Network?): HttpURLConnection =
        (network?.openConnection(url) ?: url.openConnection()) as HttpURLConnection

    private fun extractIndexFromFilename(filename: String): String? {
        Regex("(\\d{8}_\\d{6})\\.[^.]+$").find(filename)?.groupValues?.get(1)?.let { return it }
        val num = Regex("(\\d+)\\.[^.]+$").find(filename)?.groupValues?.get(1) ?: return null
        return num.trimStart('0').ifEmpty { "0" }
    }

    private fun extractDatetimeFromFilename(filename: String): String? {
        val clean = filename.trim().removePrefix("/")
        val m = Regex("(\\d{8})_(\\d{6})\\.[^.]+$").find(clean) ?: return null
        val (datePart, timePart) = m.destructured
        val year  = datePart.take(4)
        val month = datePart.drop(4).take(2)
        val day   = datePart.drop(6)
        val hour  = timePart.take(2)
        val min   = timePart.drop(2).take(2)
        val sec   = timePart.drop(4)
        return "$year-$month-$day $hour:$min:$sec"
    }

    private fun isImageFile(f: String) = f.endsWith(".jpg", true) || f.endsWith(".jpeg", true) || f.endsWith(".png", true)
    private fun isAudioFile(f: String) = f.endsWith(".wav", true) || f.endsWith(".mp3", true) || f.endsWith(".m4a", true)
}
