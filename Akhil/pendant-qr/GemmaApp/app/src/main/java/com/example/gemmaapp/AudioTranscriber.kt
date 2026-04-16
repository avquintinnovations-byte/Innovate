package com.example.gemmaapp

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.io.RandomAccessFile

/**
 * Transcribes WAV audio files using Vosk (offline speech recognition).
 * Expects 16kHz mono 16-bit PCM. Other formats may need conversion.
 */
class AudioTranscriber(private val context: Context) {

    private var model: Model? = null

    /**
     * Ensures Vosk model is loaded. Extracts from assets to filesDir on first use.
     */
    fun ensureModel(): Boolean {
        if (model != null) return true
        return try {
            val modelDir = File(context.filesDir, "vosk-model-small-en-us-0.15")
            if (!modelDir.exists() || modelDir.list()?.isEmpty() == true) {
                modelDir.mkdirs()
                copyModelFromAssets(modelDir)
            }
            model = Model(modelDir.absolutePath)
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun copyModelFromAssets(targetDir: File) {
        val assetPath = "vosk-model-small-en-us-0.15"
        fun copyRecursively(assetPrefix: String, target: File) {
            val list = context.assets.list(assetPrefix) ?: return
            target.mkdirs()
            for (name in list) {
                val subAsset = "$assetPrefix/$name"
                val subList = context.assets.list(subAsset)
                if (subList.isNullOrEmpty()) {
                    File(target, name).outputStream().use { out ->
                        context.assets.open(subAsset).use { it.copyTo(out) }
                    }
                } else {
                    copyRecursively(subAsset, File(target, name))
                }
            }
        }
        copyRecursively(assetPath, targetDir)
    }

    /**
     * Transcribes with word-level timestamps for sync during playback.
     * Returns list of (word, startTimeSeconds) or null.
     */
    fun transcribeWithWordTimings(audioFile: File): List<Pair<String, Float>>? {
        val m = model ?: return null
        return try {
            val (pcmData, sampleRate) = readWavPcm(audioFile) ?: return null
            val recognizer = Recognizer(m, sampleRate.toFloat())
            try { recognizer.javaClass.getMethod("setWords", Boolean::class.javaPrimitiveType).invoke(recognizer, true) } catch (_: Exception) { }
            val words = mutableListOf<Pair<String, Float>>()
            val chunkSize = 4096
            var offset = 0
            while (offset < pcmData.size) {
                val len = minOf(chunkSize, pcmData.size - offset)
                val chunk = pcmData.copyOfRange(offset, offset + len)
                if (recognizer.acceptWaveForm(chunk, len)) {
                    parseWordsFromResult(recognizer.result, words)
                }
                offset += len
            }
            parseWordsFromResult(recognizer.finalResult, words)
            recognizer.close()
            words.takeIf { it.isNotEmpty() }
        } catch (e: Exception) {
            null
        }
    }

    private fun parseWordsFromResult(jsonStr: String, out: MutableList<Pair<String, Float>>) {
        try {
            val obj = JSONObject(jsonStr)
            val arr = obj.optJSONArray("result") ?: return
            for (i in 0 until arr.length()) {
                val w = arr.getJSONObject(i)
                val word = w.optString("word", "")
                val start = w.optDouble("start", 0.0).toFloat()
                if (word.isNotEmpty()) out.add(word to start)
            }
        } catch (_: Exception) { }
    }

    /**
     * Transcribes a WAV file.
     * Returns null if transcription fails (model/format/error).
     * Returns "" if processed successfully but no speech detected.
     * Returns non-empty string with speech text otherwise.
     */
    fun transcribe(audioFile: File): String? {
        val m = model ?: return null
        return try {
            val (pcmData, sampleRate) = readWavPcm(audioFile) ?: return null
            val recognizer = Recognizer(m, sampleRate.toFloat())
            val chunkSize = 4096
            val transcript = StringBuilder()
            var offset = 0
            while (offset < pcmData.size) {
                val len = minOf(chunkSize, pcmData.size - offset)
                val chunk = pcmData.copyOfRange(offset, offset + len)
                if (recognizer.acceptWaveForm(chunk, len)) {
                    JSONObject(recognizer.result).optString("text").takeIf { it.isNotEmpty() }?.let {
                        transcript.append(it).append(" ")
                    }
                }
                offset += len
            }
            transcript.append(JSONObject(recognizer.finalResult).optString("text"))
            recognizer.close()
            transcript.toString().trim()
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Reads WAV file, returns (samples as byte array, sample rate) or null.
     * WAV uses little-endian. Supports PCM 16/24/32-bit, float 32-bit, 8-48kHz.
     */
    private fun readWavPcm(file: File): Pair<ByteArray, Int>? {
        if (!file.exists() || file.length() < 44) return null
        return try {
            RandomAccessFile(file, "r").use { raf ->
                val chunk = ByteArray(4)
                if (raf.read(chunk) < 4) return null
                val riff = String(chunk)
                if (riff != "RIFF" && riff != "RIFX") return null
                val fileSize = readIntLE(raf)
                if (raf.read(chunk) < 4) return null
                if (String(chunk) != "WAVE") return null
                var sampleRate = 16000
                var channels = 1
                var bitsPerSample = 16
                var audioFormat = 1
                var dataOffset = 0L
                var dataSize = 0L
                val fileLen = raf.length()
                while (raf.filePointer < fileLen - 8) {
                    if (raf.read(chunk) < 4) break
                    val subChunkId = String(chunk)
                    val subChunkSize = readIntLE(raf) and 0x7FFFFFFF
                    when (subChunkId) {
                        "fmt " -> {
                            audioFormat = readShortLE(raf)
                            channels = readShortLE(raf)
                            sampleRate = readIntLE(raf)
                            readIntLE(raf)
                            readShortLE(raf)
                            bitsPerSample = readShortLE(raf)
                            if (subChunkSize > 16) raf.skipBytes((subChunkSize - 16).coerceAtMost(1024))
                        }
                        "data" -> {
                            dataOffset = raf.filePointer
                            dataSize = subChunkSize.toLong() and 0xFFFFFFFFL
                            if (dataSize > 0) break
                        }
                        else -> raf.skipBytes(subChunkSize.coerceAtMost(1024 * 1024))
                    }
                }
                if (dataSize <= 0 || dataOffset + dataSize > fileLen) return null
                val rawData = ByteArray(dataSize.toInt())
                raf.seek(dataOffset)
                raf.readFully(rawData)
                val samples = convertTo16BitMono(rawData, channels, bitsPerSample, audioFormat)
                      ?: return null
                val resampled = resampleTo16kHz(samples, sampleRate) ?: return null
                Pair(resampled.first, resampled.second)
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun convertTo16BitMono(raw: ByteArray, channels: Int, bitsPerSample: Int, format: Int): ByteArray? {
        val bytesPerSample = when (bitsPerSample) {
            8 -> 1
            16 -> 2
            24 -> 3
            32 -> 4
            else -> return null
        }
        val frameCount = raw.size / (bytesPerSample * channels)
        val out = ByteArray(frameCount * 2)
        for (i in 0 until frameCount) {
            var sum = 0
            for (c in 0 until channels) {
                val idx = (i * channels + c) * bytesPerSample
                if (idx + bytesPerSample > raw.size) break
                val sample = when (bitsPerSample) {
                    8 -> ((raw[idx].toInt() and 0xff) - 128) shl 8
                    16 -> (raw[idx].toInt() and 0xff) or (raw[idx + 1].toInt() shl 8)
                    24 -> (raw[idx].toInt() and 0xff) or ((raw[idx + 1].toInt() and 0xff) shl 8) or (raw[idx + 2].toInt() shl 16)
                    32 -> when (format) {
                        1 -> (raw[idx].toInt() and 0xff) or (raw[idx + 1].toInt() shl 8) or (raw[idx + 2].toInt() shl 16) or (raw[idx + 3].toInt() shl 24).let { v -> (v shr 16).coerceIn(-32768, 32767) }
                        3 -> {
                            val f = java.lang.Float.intBitsToFloat(
                                (raw[idx].toInt() and 0xff) or (raw[idx + 1].toInt() and 0xff shl 8) or
                                (raw[idx + 2].toInt() and 0xff shl 16) or (raw[idx + 3].toInt() and 0xff shl 24)
                            )
                            (f * 32767).toInt().coerceIn(-32768, 32767)
                        }
                        else -> 0
                    }
                    else -> 0
                }
                sum += sample
            }
            val mono = (sum / channels).coerceIn(-32768, 32767)
            out[i * 2] = (mono and 0xff).toByte()
            out[i * 2 + 1] = (mono shr 8).toByte()
        }
        return out
    }

    private fun readShortLE(raf: RandomAccessFile): Int {
        val b0 = raf.read()
        val b1 = raf.read()
        return (b0 and 0xff) or ((b1 and 0xff) shl 8)
    }

    private fun readIntLE(raf: RandomAccessFile): Int {
        val b0 = raf.read()
        val b1 = raf.read()
        val b2 = raf.read()
        val b3 = raf.read()
        return (b0 and 0xff) or ((b1 and 0xff) shl 8) or ((b2 and 0xff) shl 16) or ((b3 and 0xff) shl 24)
    }

    private fun resampleTo16kHz(samples: ByteArray, sampleRate: Int): Pair<ByteArray, Int>? {
        return when {
            sampleRate == 16000 -> Pair(samples, 16000)
            sampleRate == 8000 -> Pair(samples, 8000)
            sampleRate == 48000 -> downsample(samples, 3)
            sampleRate == 44100 -> downsample(samples, 3)
            sampleRate == 32000 -> downsample(samples, 2)
            sampleRate == 22050 -> downsample(samples, 2)
            sampleRate == 11025 -> Pair(samples, 11025)
            sampleRate == 96000 -> downsample(samples, 6)
            else -> null
        }
    }

    private fun downsample(samples: ByteArray, factor: Int): Pair<ByteArray, Int> {
        val inFrames = samples.size / 2
        val outFrames = inFrames / factor
        val out = ByteArray(outFrames * 2)
        for (i in 0 until outFrames) {
            val srcIdx = i * factor
            if (srcIdx * 2 + 1 < samples.size) {
                out[i * 2] = samples[srcIdx * 2]
                out[i * 2 + 1] = samples[srcIdx * 2 + 1]
            }
        }
        return Pair(out, 16000)
    }

    fun release() {
        model?.close()
        model = null
    }
}
