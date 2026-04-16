package com.example.gemmaapp

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.mediapipe.tasks.text.textembedder.TextEmbedder
import io.objectbox.Box
import org.json.JSONArray
import kotlin.concurrent.thread
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * Transfers files from ESP32 pendant to the app via BLE GATT.
 *
 * Protocol (both sides must agree on UUIDs and packet format):
 *   Phone → ESP32 CMD char (write no-response):
 *     "LIST"       → ESP32 pushes L-chunks then X
 *     "GET:<path>" → ESP32 opens file, auto-sends first D-chunk
 *     "NEXT"       → ESP32 sends next D-chunk
 *     "ABORT"      → cancel current transfer
 *   ESP32 → Phone DATA char (notify), first byte = type:
 *     'L' (0x4C) + bytes → list JSON fragment
 *     'D' (0x44) + bytes → file data chunk
 *     'X' (0x58)         → end of list or file
 *     'E' (0x45) + msg   → error string
 */
object BleSyncHelper {

    private const val TAG = "BleSyncHelper"
    private const val DEVICE_NAME = "Memorable"

    // Index service UUID — present in ALL firmware versions (old and new)
    private val INDEX_SERVICE_UUID = UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
    // File-transfer service — only present after the updated firmware is flashed
    private val XFER_SERVICE_UUID  = UUID.fromString("4fafc201-1fb5-459e-8fcc-c5c9c331914b")
    private val XFER_CMD_CHAR_UUID  = UUID.fromString("beb5483e-36e1-4688-b7f5-ea07361b26a8")
    private val XFER_DATA_CHAR_UUID = UUID.fromString("beb5483f-36e1-4688-b7f5-ea07361b26a8")
    private val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    private const val SCAN_TIMEOUT_MS = 15_000L
    private const val CONNECT_TIMEOUT_MS = 15_000L
    private const val SERVICES_TIMEOUT_MS = 10_000L
    private const val NOTIF_ENABLE_TIMEOUT_MS = 5_000L
    private const val LIST_TIMEOUT_MS = 20_000L
    private const val CHUNK_TIMEOUT_MS = 30_000L  // per chunk / per file when small

    // Sentinel values placed on notifyQueue to signal special conditions
    private val END_SENTINEL = ByteArray(0)       // 'X' received
    private val LOST_SENTINEL = ByteArray(1) { 0xFF.toByte() }  // connection lost

    // ---- GATT state (only accessed on BLE callback thread or while holding gattLock) ----
    private var activeGatt: BluetoothGatt? = null
    private var xferCmdChar: BluetoothGattCharacteristic? = null
    private var xferDataChar: BluetoothGattCharacteristic? = null

    private val connectedLatch   = CountDownLatch(1)
    private val servicesLatch    = CountDownLatch(1)
    private val notifEnabledLatch = CountDownLatch(1)
    private val notifyQueue = LinkedBlockingQueue<ByteArray>(512)

    // Reset all sync-session state so we can start fresh each call
    private fun resetState() {
        notifyQueue.clear()
        xferCmdChar = null
        xferDataChar = null
        activeGatt?.close()
        activeGatt = null
    }

    // ---- Public entry point ----

    fun sync(
        context: Context,
        embedder: TextEmbedder?,
        box: Box<Knowledge>?,
        onComplete: (newCount: Int, message: String) -> Unit,
        onFilesFound: ((count: Int) -> Unit)? = null,
        onMemoryReady: ((record: Knowledge) -> Unit)? = null
    ) {
        if (box == null)     { onComplete(0, "Database not available"); return }
        if (embedder == null) { onComplete(0, "Embedder not ready"); return }

        (context.applicationContext as? GemmaApp)?.pauseBleForSync()

        thread {
            // Give the ESP32 time to restart advertising after BleIndexManager disconnects.
            // BleIndexManager.stop() closes the GATT connection; the ESP32's onDisconnect
            // callback then calls pBleAdvertising->start(). 2.5 s is enough for that cycle.
            Thread.sleep(2500)
            try {
                val result = runSync(context, embedder, box, onFilesFound, onMemoryReady)
                onComplete(result.first, result.second)
            } catch (e: Exception) {
                Log.e(TAG, "BLE sync failed", e)
                onComplete(0, "BLE sync failed: ${e.message}")
            } finally {
                cleanup()
                (context.applicationContext as? GemmaApp)?.resumeBleAfterSync()
            }
        }
    }

    private val mainHandler = Handler(Looper.getMainLooper())

    @SuppressLint("MissingPermission")
    private fun runSync(
        context: Context,
        embedder: TextEmbedder,
        box: Box<Knowledge>,
        onFilesFound: ((count: Int) -> Unit)? = null,
        onMemoryReady: ((record: Knowledge) -> Unit)? = null
    ): Pair<Int, String> {

        if (!checkPermissions(context)) return 0 to "Bluetooth permission required"

        val bluetoothAdapter = (context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)
            ?.adapter ?: return 0 to "Bluetooth not available"
        if (!bluetoothAdapter.isEnabled) return 0 to "Bluetooth is off"

        // 1. Find the pendant. Prefer the MAC cached by BleIndexManager so we can
        //    skip scanning entirely — a fresh scan right after BleIndexManager was
        //    active often trips Android's SCAN_FAILED_SCANNING_TOO_FREQUENTLY throttle
        //    (5 scan-starts per 30 s). Only fall back to scanning if the cached MAC
        //    is missing or the direct connect below fails.
        val cachedMac = (context.applicationContext as? GemmaApp)?.lastPendantMac
        var device: BluetoothDevice? = if (cachedMac != null) {
            try {
                Log.d(TAG, "Using cached pendant MAC $cachedMac (skipping scan)")
                bluetoothAdapter.getRemoteDevice(cachedMac)
            } catch (_: Exception) { null }
        } else null

        if (device == null) {
            Log.d(TAG, "No cached MAC — scanning with retries")
            for (attempt in 1..3) {
                device = scanForDevice(context, bluetoothAdapter)
                if (device != null) break
                Log.w(TAG, "Scan attempt $attempt failed — retrying after short wait")
                Thread.sleep(1500)
            }
        }
        if (device == null)
            return 0 to "Pendant not found (make sure Bluetooth is on and pendant is nearby)"

        // 2. Connect
        val connLatch   = CountDownLatch(1)
        val svcLatch    = CountDownLatch(1)
        val notifLatch  = CountDownLatch(1)
        notifyQueue.clear()

        val gattCallback = buildGattCallback(connLatch, svcLatch, notifLatch)
        val gatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        activeGatt = gatt

        if (!connLatch.await(CONNECT_TIMEOUT_MS, TimeUnit.MILLISECONDS))
            return 0 to "BLE connect timed out"
        if (!svcLatch.await(SERVICES_TIMEOUT_MS, TimeUnit.MILLISECONDS))
            return 0 to "Service discovery timed out"

        val cmdChar  = xferCmdChar  ?: return 0 to
            "Pendant firmware needs updating — flash the new .ino to enable BLE file transfer"
        val dataChar = xferDataChar ?: return 0 to "Transfer DATA characteristic not found"

        // Enable notifications on DATA characteristic
        gatt.setCharacteristicNotification(dataChar, true)
        val cccd = dataChar.getDescriptor(CCCD_UUID)
        if (cccd != null) {
            writeDescriptor(gatt, cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
            if (!notifLatch.await(NOTIF_ENABLE_TIMEOUT_MS, TimeUnit.MILLISECONDS))
                Log.w(TAG, "Notification enable timed out — proceeding anyway")
        }

        // 3. Request maximum MTU (matches ESP32 setMTU(517); notify payload = 514 bytes)
        gatt.requestMtu(517)
        Thread.sleep(300)

        // 3b. Request 1M PHY explicitly (matches firmware). 1M is the universal
        //     BLE default — more reliable across Android stacks than 2M.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            try {
                gatt.setPreferredPhy(
                    BluetoothDevice.PHY_LE_1M_MASK,
                    BluetoothDevice.PHY_LE_1M_MASK,
                    BluetoothDevice.PHY_OPTION_NO_PREFERRED
                )
            } catch (_: Exception) { }
        }
        Thread.sleep(300)  // settle MTU + PHY + connection-interval negotiation

        // 4. Get file list — retry up to 3 times. The first LIST after a fresh GATT
        //    connection sometimes drops the opening bytes of the first notification
        //    (Android BT stack / early MTU-settle race), which destroys the JSON.
        //    A second LIST command on the same connection reliably returns the full list.
        var files: List<String> = emptyList()
        for (attempt in 1..3) {
            files = getFileList(gatt, cmdChar)
            if (files.isNotEmpty()) break
            Log.w(TAG, "LIST attempt $attempt returned empty — retrying after 500 ms")
            Thread.sleep(500)
        }
        Log.d(TAG, "BLE file list: $files")

        // 5. Determine which files need downloading
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

        val imagesDir = File(context.filesDir, "knowledge_images").apply { mkdirs() }
        val audioDir  = File(context.filesDir, "knowledge_audio").apply { mkdirs() }
        val transcriber = AudioTranscriber(context)
        var newCount = 0

        // 6. Download index.txt for captions
        val indexMap = mutableMapOf<String, String>()
        if (files.contains("index.txt")) {
            val bytes = downloadFile(gatt, cmdChar, "index.txt")
            bytes.toString(Charsets.UTF_8).split("\n").forEach { line ->
                val trimmed = line.trim()
                if (trimmed.contains(",") || trimmed.contains("\t")) {
                    val parts = trimmed.split(Regex("[,\t]"), limit = 2)
                    if (parts.size >= 2) indexMap[parts[0].trim()] = parts[1].trim()
                }
            }
        }

        // 7. Identify new image files; build index→audioFilename lookup for pairing
        val newImageFiles = files.filter { it != "index.txt" && it !in existingFilenames && isImageFile(it) }
        // Map timestamp index (e.g. "20250216_143022") → audio filename for quick pairing
        val audioByIndex: Map<String, String> = files
            .filter { isAudioFile(it) }
            .mapNotNull { f -> extractIndexFromFilename(f)?.let { it to f } }
            .toMap()

        if (onFilesFound != null && newImageFiles.isNotEmpty()) {
            mainHandler.post { onFilesFound(newImageFiles.size) }
        }

        // 8. Download each image then its paired audio. Each image is wrapped in
        //    try/catch so one corrupted file (e.g. SD has the file entry but only
        //    partial data) doesn't abort the entire sync — just skip and continue.
        var skippedCount = 0
        for (imageFilename in newImageFiles) {
            val imageBytes: ByteArray = try {
                downloadFile(gatt, cmdChar, imageFilename)
            } catch (e: Exception) {
                Log.e(TAG, "Skipping $imageFilename — ${e.message}")
                skippedCount++
                continue
            }
            val imageFile = File(imagesDir, "esp32_${System.currentTimeMillis()}_$imageFilename")
            FileOutputStream(imageFile).use { it.write(imageBytes) }

            val caption  = indexMap[imageFilename]
            val datetime = extractDatetimeFromFilename(imageFilename)
            val idx      = extractIndexFromFilename(imageFilename)

            // Find the matching audio file (same timestamp index, not previously synced)
            val audioFilename = idx?.let { audioByIndex[it] }?.takeIf { it !in existingFilenames }

            var audioPath:    String?     = null
            var finalContent: String?     = caption
            var finalVector:  FloatArray? = if (!caption.isNullOrEmpty())
                embedder.embed(caption).embeddingResult().embeddings().first().floatEmbedding()
            else null

            if (audioFilename != null) {
                try {
                    val audioBytes = downloadFile(gatt, cmdChar, audioFilename)
                    val audioFile  = File(audioDir, "esp32_${System.currentTimeMillis()}_$audioFilename")
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
                } catch (e: Exception) {
                    Log.w(TAG, "Audio download failed for $audioFilename, saving image only: ${e.message}")
                    audioPath = null  // image record saved without audio; retroactive pass below will retry
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

        // 9. Retroactive pass: image records from a previous sync that still have no audio
        //    (e.g. audio download failed last time). Try once per record; skip on failure.
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
                val audioBytes = downloadFile(gatt, cmdChar, audioFilename)
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
                Log.w(TAG, "Retroactive audio sync failed for $audioFilename: ${e.message}")
            }
        }

        val msg = when {
            newCount > 0 && skippedCount > 0 ->
                "Synced $newCount memories, skipped $skippedCount (pendant SD card may have corrupted files — consider reformatting)"
            newCount > 0 -> "Synced via BLE: $newCount new memories"
            skippedCount > 0 ->
                "Skipped $skippedCount files (pendant SD card may have corrupted files — try reformatting the SD card)"
            else -> "No new files"
        }
        return newCount to msg
    }

    // ---- BLE operations ----

    @SuppressLint("MissingPermission")
    private fun scanForDevice(context: Context, adapter: BluetoothAdapter): BluetoothDevice? {
        var found: BluetoothDevice? = null
        val latch = CountDownLatch(1)
        val scanner = adapter.bluetoothLeScanner ?: return null

        // Use two filters (OR logic): match by XFER service UUID (new firmware) OR by
        // INDEX service UUID (old firmware). This way we find the pendant regardless of
        // whether the updated firmware has been flashed yet.
        // After connecting we check whether the XFER service actually exists.
        val filters = listOf(
            ScanFilter.Builder().setServiceUuid(ParcelUuid(XFER_SERVICE_UUID)).build(),
            ScanFilter.Builder().setServiceUuid(ParcelUuid(INDEX_SERVICE_UUID)).build()
        )
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                // Accept any result matching our filters; name may be null on Android ≤ 11.
                val name = result.device.name
                if (name == null || name == DEVICE_NAME) {
                    found = result.device
                    scanner.stopScan(this)
                    latch.countDown()
                }
            }
            override fun onScanFailed(errorCode: Int) {
                Log.e(TAG, "Scan failed: $errorCode")
                latch.countDown()
            }
        }

        scanner.startScan(filters, settings, cb)
        latch.await(SCAN_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        try { scanner.stopScan(cb) } catch (_: Exception) { }
        return found
    }

    @SuppressLint("MissingPermission")
    private fun buildGattCallback(
        connLatch: CountDownLatch,
        svcLatch: CountDownLatch,
        notifLatch: CountDownLatch
    ) = object : BluetoothGattCallback() {

        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    Log.d(TAG, "GATT connected, discovering services")
                    gatt.discoverServices()
                    connLatch.countDown()
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    Log.d(TAG, "GATT disconnected (status=$status)")
                    notifyQueue.offer(LOST_SENTINEL)
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Log.e(TAG, "Service discovery failed: $status")
                svcLatch.countDown()
                return
            }
            val xferSvc = gatt.getService(XFER_SERVICE_UUID)
            if (xferSvc == null) {
                Log.e(TAG, "Transfer service not found on device")
            } else {
                xferCmdChar  = xferSvc.getCharacteristic(XFER_CMD_CHAR_UUID)
                xferDataChar = xferSvc.getCharacteristic(XFER_DATA_CHAR_UUID)
                Log.d(TAG, "Transfer service found — CMD=$xferCmdChar DATA=$xferDataChar")
            }
            svcLatch.countDown()
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int
        ) {
            if (descriptor.characteristic?.uuid == XFER_DATA_CHAR_UUID) {
                notifLatch.countDown()
            }
        }

        // Confirms the actually-negotiated PHY. If txPhy/rxPhy == PHY_LE_2M (2) then
        // 2M PHY is in use. If either is PHY_LE_1M (1) the central/peripheral didn't
        // support BT5 and we fell back to 1 Mbps.
        override fun onPhyUpdate(gatt: BluetoothGatt, txPhy: Int, rxPhy: Int, status: Int) {
            Log.d(TAG, "PHY update: tx=$txPhy rx=$rxPhy status=$status (2 = 2M PHY)")
        }

        override fun onPhyRead(gatt: BluetoothGatt, txPhy: Int, rxPhy: Int, status: Int) {
            Log.d(TAG, "PHY read: tx=$txPhy rx=$rxPhy")
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            Log.d(TAG, "MTU negotiated: $mtu (max notify payload = ${mtu - 3})")
        }

        // API < 33
        @Deprecated("Deprecated in API 33")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic
        ) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
                characteristic.value?.let { enqueueNotify(it) }
            }
        }

        // API 33+
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray
        ) {
            enqueueNotify(value)
        }

        private fun enqueueNotify(value: ByteArray) {
            if (value.isEmpty()) return
            when (value[0].toInt() and 0xFF) {
                // 'X' — 1-byte END is legacy; 5-byte END carries the file size for
                // truncation detection. Pass the full packet through in that case.
                0x58 -> notifyQueue.offer(if (value.size == 1) END_SENTINEL else value.copyOf())
                // 'W' warmup — absorbs the first-notification byte-drop; ignore.
                0x57 -> { }
                else -> notifyQueue.offer(value.copyOf())   // 'L', 'D', 'E'
            }
        }
    }

    // Write CCCD descriptor (works for all API levels)
    @SuppressLint("MissingPermission")
    private fun writeDescriptor(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, value: ByteArray) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(descriptor, value)
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = value
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(descriptor)
        }
    }

    // Write command to CMD characteristic without waiting for GATT ACK (fast)
    @SuppressLint("MissingPermission")
    private fun writeCommand(gatt: BluetoothGatt, char: BluetoothGattCharacteristic, cmd: String) {
        val bytes = cmd.toByteArray(Charsets.UTF_8)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeCharacteristic(char, bytes, BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
        } else {
            @Suppress("DEPRECATION")
            char.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            @Suppress("DEPRECATION")
            char.value = bytes
            @Suppress("DEPRECATION")
            gatt.writeCharacteristic(char)
        }
    }

    private fun getFileList(gatt: BluetoothGatt, cmdChar: BluetoothGattCharacteristic): List<String> {
        val BURST_SIZE = 4  // must match BXFER_BURST_SIZE in firmware
        notifyQueue.clear()
        writeCommand(gatt, cmdChar, "LIST")
        val out = ByteArrayOutputStream()
        val deadline = System.currentTimeMillis() + LIST_TIMEOUT_MS
        var chunksInBurst = 0
        while (true) {
            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0) throw Exception("LIST timed out")
            val packet = notifyQueue.poll(remaining, TimeUnit.MILLISECONDS)
                ?: throw Exception("LIST timed out")
            if (packet === LOST_SENTINEL) throw Exception("BLE connection lost during LIST")
            if (packet === END_SENTINEL) break
            // 'L' packet: byte 0 is type, rest is JSON
            if (packet.isNotEmpty() && (packet[0].toInt() and 0xFF) == 0x4C) {
                out.write(packet, 1, packet.size - 1)
                chunksInBurst++
                if (chunksInBurst >= BURST_SIZE) {
                    writeCommand(gatt, cmdChar, "NEXT")  // open next burst window
                    chunksInBurst = 0
                }
            } else if (packet.isNotEmpty() && (packet[0].toInt() and 0xFF) == 0x45) {
                // 'E' error
                throw Exception("ESP32 error: ${String(packet, 1, packet.size - 1, Charsets.UTF_8)}")
            }
        }
        val json = out.toString(Charsets.UTF_8.name()).trim()
        Log.d(TAG, "LIST received ${json.length} bytes: ${json.take(500)}${if (json.length > 500) "…(truncated in log)" else ""}")
        if (json.isEmpty()) return emptyList()
        // Try strict JSON parse first. If that fails (most commonly because the first
        // few bytes of the BLE notification were dropped, which destroys the opening
        // `["` of the array), fall back to regex extraction of valid filenames.
        try {
            val arr = JSONArray(json)
            val files = (0 until arr.length()).mapNotNull { arr.optString(it).ifEmpty { null } }
            Log.d(TAG, "LIST parsed ${files.size} files")
            return files
        } catch (e: Exception) {
            Log.w(TAG, "LIST JSON malformed (${e.message}) — falling back to regex extraction")
        }
        // Regex fallback: any bare `image_*.jpg/png/jpeg`, `audio_*.wav/mp3/m4a`, or
        // `*.txt` token. The leading (possibly truncated) entry won't match the
        // `image_` prefix and is silently dropped — but all other entries recover.
        val fallback = Regex("""(image_[0-9_a-zA-Z]+\.(?:jpg|jpeg|png)|audio_[0-9_a-zA-Z]+\.(?:wav|mp3|m4a)|index\.txt)""")
            .findAll(json)
            .map { it.value }
            .distinct()
            .toList()
        Log.w(TAG, "LIST regex fallback recovered ${fallback.size} files")
        return fallback
    }

    private fun downloadFile(gatt: BluetoothGatt, cmdChar: BluetoothGattCharacteristic, path: String): ByteArray {
        // One attempt per file. Retries on stalls are pointless — if the ESP32
        // couldn't send chunks the first time (SD.open() hang on a corrupted
        // file, bad cluster chain, etc.), it won't succeed on a second try and
        // we'd just waste another ~60 s per file. The outer sync loop catches
        // the exception and skips the file; the user can reformat the SD card
        // to eliminate corrupted entries.
        return doDownloadFile(gatt, cmdChar, path)
    }

    private fun doDownloadFile(gatt: BluetoothGatt, cmdChar: BluetoothGattCharacteristic, path: String): ByteArray {
        // Settle before GET so ESP32's main loop finishes post-EOF cleanup from
        // the previous file before starting the new one.
        Thread.sleep(150)
        notifyQueue.clear()
        val BURST_SIZE = 4  // must match BXFER_BURST_SIZE in firmware
        writeCommand(gatt, cmdChar, "GET:$path")
        val out = ByteArrayOutputStream()
        val overallDeadline = System.currentTimeMillis() + 300_000L  // 5-min cap per file
        var stalledNudges = 0
        var chunksInBurst = 0
        // Longer first-chunk wait (SD.open + warmup + first burst can take > 2s
        // on a slow SD; pendant's corrupted files can take up to 30s to fail).
        // Subsequent chunks are tightened since real transfer is much faster.
        var pollTimeoutMs = 10_000L  // 10 s for the first chunk
        while (true) {
            if (System.currentTimeMillis() > overallDeadline)
                throw Exception("Download exceeded overall timeout: $path")
            val packet = notifyQueue.poll(pollTimeoutMs, TimeUnit.MILLISECONDS)
            if (packet == null) {
                if (++stalledNudges > 6) throw Exception("Download stalled: $path")
                Log.w(TAG, "No chunk for ${pollTimeoutMs}ms on $path — nudging (attempt $stalledNudges)")
                writeCommand(gatt, cmdChar, "NEXT")
                chunksInBurst = 0
                continue
            }
            stalledNudges = 0
            pollTimeoutMs = 3000L
            if (packet === LOST_SENTINEL) throw Exception("BLE connection lost downloading $path")
            if (packet === END_SENTINEL) break  // legacy 1-byte END — no size verification
            when (packet[0].toInt() and 0xFF) {
                0x44 -> {  // 'D' data chunk
                    val chunkDataSize = packet.size - 1
                    out.write(packet, 1, chunkDataSize)
                    chunksInBurst++
                    Log.v(TAG, "chunk: size=$chunkDataSize total=${out.size()}")
                    if (chunksInBurst >= BURST_SIZE) {
                        writeCommand(gatt, cmdChar, "NEXT")
                        chunksInBurst = 0
                    }
                }
                0x58 -> {  // 'X' END with 4-byte size — verify completeness
                    val claimed = if (packet.size >= 5) {
                        (packet[1].toInt() and 0xFF)         or
                        ((packet[2].toInt() and 0xFF) shl 8)  or
                        ((packet[3].toInt() and 0xFF) shl 16) or
                        ((packet[4].toInt() and 0xFF) shl 24)
                    } else -1
                    val received = out.size()
                    if (claimed >= 0 && received != claimed)
                        throw Exception("Size mismatch for $path: got $received, expected $claimed — will retry")
                    Log.d(TAG, "Downloaded $path: $received bytes (size verified)")
                    return out.toByteArray()
                }
                0x45 -> throw Exception("ESP32 error for $path: ${String(packet, 1, packet.size - 1, Charsets.UTF_8)}")
            }
        }
        return out.toByteArray()
    }

    @SuppressLint("MissingPermission")
    private fun cleanup() {
        try { activeGatt?.close() } catch (_: Exception) { }
        activeGatt = null
        xferCmdChar = null
        xferDataChar = null
        notifyQueue.clear()
    }

    // ---- Helpers (mirrors Esp32SyncHelper) ----

    private fun checkPermissions(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Android 12+: need BLUETOOTH_CONNECT + BLUETOOTH_SCAN (no location needed)
            val hasConnect = ContextCompat.checkSelfPermission(
                context, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
            val hasScan = ContextCompat.checkSelfPermission(
                context, Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
            if (!hasConnect || !hasScan) {
                Log.w(TAG, "Missing BLE permissions (Android 12+): connect=$hasConnect scan=$hasScan")
                return false
            }
        } else {
            // Android ≤ 11: BLE scanning requires ACCESS_FINE_LOCATION
            val hasLocation = ContextCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
            if (!hasLocation) {
                Log.w(TAG, "Missing ACCESS_FINE_LOCATION (required for BLE on Android ≤ 11)")
                return false
            }
        }
        return true
    }

    private fun extractIndexFromFilename(filename: String): String? {
        Regex("(\\d{8}_\\d{6})\\.[^.]+$").find(filename)?.groupValues?.get(1)?.let { return it }
        val num = Regex("(\\d+)\\.[^.]+$").find(filename)?.groupValues?.get(1) ?: return null
        return num.trimStart('0').ifEmpty { "0" }
    }

    private fun extractDatetimeFromFilename(filename: String): String? {
        val clean = filename.trim().removePrefix("/")
        val m = Regex("(\\d{8})_(\\d{6})\\.[^.]+$").find(clean) ?: return null
        val (datePart, timePart) = m.destructured
        return "${datePart.take(4)}-${datePart.drop(4).take(2)}-${datePart.drop(6)} " +
               "${timePart.take(2)}:${timePart.drop(2).take(2)}:${timePart.drop(4)}"
    }

    private fun isImageFile(f: String) = f.endsWith(".jpg", true) || f.endsWith(".jpeg", true) || f.endsWith(".png", true)
    private fun isAudioFile(f: String) = f.endsWith(".wav", true) || f.endsWith(".mp3", true) || f.endsWith(".m4a", true)
}
