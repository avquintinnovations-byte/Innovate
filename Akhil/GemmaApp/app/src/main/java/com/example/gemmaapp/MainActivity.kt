package com.example.gemmaapp

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.graphics.BitmapFactory
import android.media.MediaPlayer
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.card.MaterialCardView
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import com.google.mediapipe.tasks.text.textembedder.TextEmbedder
import io.objectbox.Box
import kotlin.concurrent.thread
import org.json.JSONObject
import java.io.File
import java.util.Calendar

class MainActivity : AppCompatActivity() {

    private lateinit var llmInference: LlmInference
    private lateinit var textEmbedder: TextEmbedder
    private var knowledgeBox: Box<Knowledge>? = null

    private var memories = mutableListOf<Knowledge>()
    private var audioByIndex = mapOf<String, Pair<String, String>>()
    private var mainGridAdapter: MainMemoryGridAdapter? = null

    private var isLlmReady = false
    private var isEmbedderReady = false
    private var isDbReady = false


    private val addKnowledgeLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            Toast.makeText(this, "Memory saved", Toast.LENGTH_SHORT).show()
            loadMemories()
            refreshPendantIndicator()
        }
    }

    /** Show pendant index vs synced count; uses persisted value so it shows on app reopen */
    private fun refreshPendantIndicator() {
        val txt = findViewById<TextView>(R.id.txtPendantIndex)
        val app = application as GemmaApp
        val idx = app.lastPendantIndex
        if (idx < 0) return
        val synced = app.getSyncedEsp32Count()
        val newCount = (idx - synced).coerceAtLeast(0)
        txt.text = when {
            newCount > 0 -> "$newCount new memories"
            idx > 0 -> "Up to date"
            else -> "Pendant: $idx"
        }
        txt.visibility = View.VISIBLE
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val inputPrompt = findViewById<EditText>(R.id.inputPrompt)
        val btnAsk = findViewById<Button>(R.id.btnAsk)
        val btnAddKnowledge = findViewById<Button>(R.id.btnAddKnowledge)
        val txtResponse = findViewById<TextView>(R.id.txtResponse)
        val txtMemoryStats = findViewById<TextView>(R.id.txtMemoryStats)
        val lblMemories = findViewById<TextView>(R.id.lblMemories)
        val gridMemories = findViewById<GridView>(R.id.gridMemories)
        val txtEmptyMemories = findViewById<TextView>(R.id.txtEmptyMemories)

        // 1. Use singleton ObjectBox from Application (single store for entire app)
        val store = (application as GemmaApp).boxStore
        knowledgeBox = store?.boxFor(Knowledge::class.java)
        isDbReady = (knowledgeBox != null)
        if (!isDbReady) {
            txtResponse.text = "Database error. Try: Settings > Apps > GemmaApp > Clear data"
        }
        refreshMemoryCount()
        loadMemories()

        // 2. Initialize Models (run in background)
        if (isDbReady) {
            setupLLM()
            setupEmbedder()
        }

        btnAddKnowledge.setOnClickListener {
            addKnowledgeLauncher.launch(Intent(this, AddKnowledgeActivity::class.java))
        }

        val app = application as GemmaApp
        val btnSync = findViewById<Button>(R.id.btnSyncEsp32)
        val syncProgressBar = findViewById<ProgressBar>(R.id.syncProgressBar)

        btnSync.setOnClickListener {
            if (!isEmbedderReady || !isDbReady) {
                Toast.makeText(this, "Please wait for models to load", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            btnSync.isEnabled = false
            btnSync.text = ""
            syncProgressBar.visibility = View.VISIBLE
            Esp32SyncHelper.sync(this, textEmbedder, knowledgeBox) { _, message ->
                runOnUiThread {
                    btnSync.isEnabled = true
                    btnSync.text = "Sync"
                    syncProgressBar.visibility = View.GONE
                    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
                    loadMemories()
                    refreshPendantIndicator()
                }
            }
        }

        findViewById<Button>(R.id.btnDeleteAll).setOnClickListener {
            showDeleteAllConfirm()
        }

        refreshPendantIndicator()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_SCAN), 100)
            }
        }
        app.initBleIndexManager(
            onIndexReceived = { _ -> runOnUiThread { refreshPendantIndicator() } },
            onConnectionChanged = { }
        )

        gridMemories.setOnItemClickListener { _, _, position, _ ->
            val record = memories[position]
            val score = mainGridAdapter?.getSimilarityForPosition(position)
            showRetrievedOverlay(record, score)
        }

        btnAsk.setOnClickListener {
            if (!isDbReady) return@setOnClickListener
            if (!isLlmReady || !isEmbedderReady) {
                txtResponse.text = "Models are still loading..."
                return@setOnClickListener
            }

            val userQuery = inputPrompt.text.toString()
            if (userQuery.isNotEmpty()) {
                txtResponse.text = "Searching & Thinking..."

                thread {
                    try {
                        val parsed = extractTimeFilterAndParse(userQuery)
                        val scoredRecords = searchRecords(parsed.semanticQuery, parsed.dateRange)

                        runOnUiThread {
                            if (isFinishing) return@runOnUiThread
                            val (highlightedId, similarity) = when {
                                scoredRecords.isNotEmpty() -> {
                                    val (record, score) = scoredRecords.first()
                                    val imageRecord = if (record.imagePath != null) record
                                        else memories.find { extractIndexFromRecord(it) == extractIndexFromRecord(record) }
                                    imageRecord?.id to score
                                }
                                else -> null to null
                            }
                            mainGridAdapter?.setHighlighted(highlightedId, similarity)
                            val pos = memories.indexOfFirst { it.id == highlightedId }
                            if (pos >= 0) gridMemories.smoothScrollToPosition(pos)
                        }

                        val records = scoredRecords.map { it.first }
                        val maxContextChars = 3000
                        val memoryContext = records.joinToString("\n---\n") { rec ->
                            rec.content ?: ""
                        }.take(maxContextChars)

                        val response = if (memoryContext.isEmpty()) {
                            val filterHint = parsed.filterLabel?.let { " (filtered by: $it)" } ?: ""
                            "No matching memories found$filterHint. Try a broader time range, or add memories using \"+ Add Memory\"."
                        } else {
                            try {
                                val finalPrompt = sanitizeForUtf8(buildRagPrompt(userQuery, memoryContext, parsed.filterLabel))
                                llmInference.generateResponse(finalPrompt)
                            } catch (e: Throwable) {
                                "Gemma error: ${e.message ?: "Model may have crashed. Try a shorter question or restart the app."}"
                            }
                        }

                        runOnUiThread {
                            if (!isFinishing) txtResponse.text = response
                        }
                    } catch (e: Exception) {
                        runOnUiThread {
                            if (!isFinishing) txtResponse.text = "Error: ${e.message}"
                        }
                    }
                }
            }
        }
    }

    /**
     * Use LLM to extract time/date filter from user query. Handles natural phrasing:
     * "what I captured earlier", "stuff from the other day", "recent memories" etc.
     * Falls back to keyword parsing if LLM fails.
     */
    private fun extractTimeFilterAndParse(userQuery: String): MemoryQueryParser.ParsedQuery {
        val now = Calendar.getInstance()
        return try {
            val filterPrompt = """Classify time filter. Reply with ONLY one word from: TODAY YESTERDAY DAY_BEFORE_YESTERDAY LAST_AFTERNOON LAST_EVENING LAST_NIGHT LAST_MORNING THIS_MORNING THIS_AFTERNOON THIS_EVENING LAST_WEEK LAST_MONTH LAST_2_WEEKS NONE

TODAY=earlier today,this day. YESTERDAY=yesterday,other day. LAST_AFTERNOON=yesterday afternoon. THIS_MORNING=today morning. LAST_WEEK=last week,past week. LAST_MONTH=last month. NONE=no time,all memories.

User: $userQuery
Filter:"""
            val response = llmInference.generateResponse(sanitizeForUtf8(filterPrompt))
            val filterKey = MemoryQueryParser.normalizeFilterFromLlmResponse(response)
            MemoryQueryParser.fromFilterKey(filterKey, userQuery, now)
        } catch (e: Throwable) {
            // Fallback to keyword parsing if LLM fails
            MemoryQueryParser.parse(userQuery, now)
        }
    }

    /** Sanitize string to valid UTF-8 to reduce MediaPipe/LLM serialization crashes */
    private fun sanitizeForUtf8(s: String): String {
        return s.replace(Regex("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F\\x7F]"), " ")
            .replace(Regex("\\p{C}"), " ")
    }

    private fun buildRagPrompt(userMessage: String, memoryContext: String, filterLabel: String?): String {
        val filterNote = filterLabel?.let { " (User asked about: $it)" } ?: ""
        return """You are a friendly memory recall assistant. Your job is to help the user remember their captured moments based on the memories below.

RULES:
- Answer ONLY using the memories provided. Never invent or assume.
- Be warm, concise, and relevant. Act like a helpful friend recalling their experiences.
- If the memories don't contain what the user asked, say so kindly.
- Keep responses brief and natural.

[ RECALLED MEMORIES ]$filterNote
$memoryContext

[ USER'S QUESTION ]
$userMessage

[ YOUR FRIENDLY RESPONSE - based only on the memories above ]"""
    }

    private fun refreshMemoryCount() {
        val count = knowledgeBox?.count() ?: 0L
        findViewById<TextView>(R.id.txtMemoryStats)?.text = "Memories: $count"
    }

    private fun loadMemories() {
        refreshMemoryCount()
        val box = knowledgeBox ?: return
        val all = box.query().build().find()
        memories = all.filter { it.imagePath != null }.toMutableList()

        audioByIndex = all
            .filter { it.audioPath != null }
            .mapNotNull { r -> extractIndexFromRecord(r)?.let { idx -> idx to Pair(r.content ?: "", r.audioPath!!) } }
            .groupBy { it.first }
            .mapValues { it.value.first().second }

        val gridMemories = findViewById<GridView>(R.id.gridMemories)
        val lblMemories = findViewById<TextView>(R.id.lblMemories)
        val txtEmptyMemories = findViewById<TextView>(R.id.txtEmptyMemories)

        if (memories.isEmpty()) {
            gridMemories.visibility = View.GONE
            lblMemories.visibility = View.GONE
            txtEmptyMemories.visibility = View.VISIBLE
        } else {
            txtEmptyMemories.visibility = View.GONE
            lblMemories.visibility = View.VISIBLE
            gridMemories.visibility = View.VISIBLE
            mainGridAdapter = MainMemoryGridAdapter(memories)
            gridMemories.adapter = mainGridAdapter
        }
    }

    private fun showDeleteAllConfirm() {
        val box = knowledgeBox ?: return
        val totalCount = box.count()
        if (totalCount == 0L) {
            Toast.makeText(this, "No memories to delete", Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Delete ALL memories?")
            .setMessage("This will permanently flush all $totalCount records from the database (including audio-only) and delete their files. This cannot be undone.")
            .setPositiveButton("Delete All") { _, _ ->
                deleteAllMemories()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun deleteAllMemories() {
        val box = knowledgeBox ?: return
        val toDelete = box.query().build().find()
        for (record in toDelete) {
            record.imagePath?.let { path ->
                File(path).takeIf { it.exists() }?.delete()
            }
            record.audioPath?.let { path ->
                File(path).takeIf { it.exists() }?.delete()
            }
            box.remove(record)
        }
        loadMemories()
        Toast.makeText(this, "All memories flushed from database", Toast.LENGTH_SHORT).show()
    }

    private fun extractIndexFromRecord(record: Knowledge): String? {
        val filename = record.metadata?.let { meta ->
            try {
                val m = meta.indexOf("\"filename\"")
                if (m < 0) return@let null
                val start = meta.indexOf("\"", m + 11) + 1
                val end = meta.indexOf("\"", start)
                if (start > 0 && end > start) meta.substring(start, end) else null
            } catch (_: Exception) { null }
        } ?: record.imagePath?.substringAfterLast('/') ?: record.audioPath?.substringAfterLast('/')
        if (filename.isNullOrEmpty()) return null
        return Regex("(\\d{8}_\\d{6})\\.[^.]+$").find(filename)?.groupValues?.get(1)
            ?: Regex("(\\d+)\\.[^.]+$").find(filename)?.groupValues?.get(1)
                ?.trimStart('0')?.ifEmpty { "0" }
    }

    /** Minimum cosine similarity (0–1) to consider a memory relevant. L2-normalized embeddings. */
    private val minRelevanceThreshold = 0.5f

    /**
     * RAG retrieval: optionally filter by date range, then cosine similarity search.
     * Returns only the single most relevant memory if it meets the relevance threshold.
     */
    private fun searchRecords(
        query: String,
        dateRange: MemoryQueryParser.DateRange?
    ): List<Pair<Knowledge, Float>> {
        val box = knowledgeBox ?: return emptyList()
        var candidates: List<Knowledge> = box.query().build().find()
        if (candidates.isEmpty()) return emptyList()

        // Apply date filter if specified
        if (dateRange != null) {
            candidates = candidates.filter { MemoryQueryParser.recordMatchesDateRange(it, dateRange) }
            if (candidates.isEmpty()) return emptyList()
        }

        val embedQuery = query.ifEmpty { "memory capture" }

        val queryVector = try {
            val emb = textEmbedder.embed(embedQuery).embeddingResult().embeddings()
            if (emb.isEmpty()) return emptyList()
            emb.first().floatEmbedding()
        } catch (e: Exception) {
            return emptyList()
        }

        return candidates
            .filter { mem -> mem.content?.isNotEmpty() == true && mem.vector != null && mem.vector!!.size == queryVector.size }
            .map { mem -> Pair(mem, cosineSimilarity(queryVector, mem.vector!!)) }
            .sortedByDescending { it.second }
            .filter { it.second >= minRelevanceThreshold }
            .take(1)
    }

    /** Dot product of L2-normalized vectors = cosine similarity */
    private fun cosineSimilarity(a: FloatArray, b: FloatArray): Float {
        require(a.size == b.size) { "Vector size mismatch" }
        var sum = 0f
        for (i in a.indices) sum += a[i] * b[i]
        return sum
    }

    /** Format metadata JSON for display: datetime only */
    private fun formatMetadataForDisplay(meta: String): String {
        return try {
            val obj = JSONObject(meta)
            obj.optString("datetime").takeIf { it.isNotEmpty() } ?: ""
        } catch (_: Exception) { "" }
    }

    private fun showRetrievedOverlay(record: Knowledge, similarityScore: Float?) {
        val overlay = LayoutInflater.from(this).inflate(R.layout.overlay_retrieved_detail, null)
        val imgDetail = overlay.findViewById<ImageView>(R.id.imgDetail)
        val audioPlaceholderDetail = overlay.findViewById<View>(R.id.audioPlaceholderDetail)
        val txtMetadataDetail = overlay.findViewById<TextView>(R.id.txtMetadataDetail)
        val txtSimilarityDetail = overlay.findViewById<TextView>(R.id.txtSimilarityDetail)
        val txtContextDetail = overlay.findViewById<TextView>(R.id.txtContextDetail)
        val btnPlayAudioDetail = overlay.findViewById<Button>(R.id.btnPlayAudioDetail)
        val btnClose = overlay.findViewById<ImageButton>(R.id.btnClose)

        when {
            record.imagePath != null && File(record.imagePath!!).exists() -> {
                BitmapFactory.decodeFile(record.imagePath)?.let {
                    imgDetail.setImageBitmap(it)
                    imgDetail.visibility = View.VISIBLE
                }
                audioPlaceholderDetail.visibility = View.GONE
            }
            record.audioPath != null -> {
                imgDetail.visibility = View.GONE
                audioPlaceholderDetail.visibility = View.VISIBLE
            }
        }

        record.metadata?.takeIf { it.isNotEmpty() }?.let { meta ->
            val formatted = formatMetadataForDisplay(meta)
            if (formatted.isNotEmpty()) {
                txtMetadataDetail.text = formatted
                txtMetadataDetail.visibility = View.VISIBLE
            }
        }

        if (similarityScore != null) {
            txtSimilarityDetail.text = "Similarity: ${"%.2f".format(similarityScore)}"
            txtSimilarityDetail.visibility = View.VISIBLE
        } else {
            txtSimilarityDetail.visibility = View.GONE
        }

        val index = extractIndexFromRecord(record)
        val pairedAudio = index?.let { audioByIndex[it] }
        val contextText = when {
            pairedAudio != null && pairedAudio.first.isNotEmpty() -> pairedAudio.first
            record.content?.isNotEmpty() == true -> record.content!!
            else -> "(No context)"
        }
        txtContextDetail.text = contextText
        txtContextDetail.visibility = View.VISIBLE

        val path = record.audioPath ?: pairedAudio?.second
        if (path != null) {
            btnPlayAudioDetail.visibility = View.VISIBLE
            val targetRecord = record.audioPath?.let { record }
                ?: knowledgeBox?.query()?.build()?.find()?.find { it.audioPath == path }
            btnPlayAudioDetail.setOnClickListener {
                transcribeAndPlay(targetRecord ?: record, path, txtContextDetail)
            }
        } else {
            btnPlayAudioDetail.visibility = View.GONE
        }

        val dialog = androidx.appcompat.app.AlertDialog.Builder(this)
            .setView(overlay)
            .create()
        dialog.window?.setBackgroundDrawableResource(android.R.color.transparent)
        btnClose.setOnClickListener { dialog.dismiss() }
        dialog.show()
    }

    private inner class MainMemoryGridAdapter(
        private val items: List<Knowledge>,
        private var highlightedId: Long? = null,
        private var highlightedSimilarity: Float? = null
    ) : BaseAdapter() {
        fun setHighlighted(id: Long?, similarity: Float?) {
            highlightedId = id
            highlightedSimilarity = similarity
            notifyDataSetChanged()
        }

        fun getSimilarityForPosition(position: Int): Float? =
            if (position in items.indices && items[position].id == highlightedId) highlightedSimilarity else null

        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = items[position].id

        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(this@MainActivity)
                .inflate(R.layout.item_memory_grid, parent, false)
            val record = items[position]
            val imgRecord = view.findViewById<ImageView>(R.id.imgRecord)
            val card = view.findViewById<MaterialCardView>(R.id.cardRoot)

            if (File(record.imagePath!!).exists()) {
                BitmapFactory.decodeFile(record.imagePath)?.let {
                    imgRecord.setImageBitmap(it)
                    imgRecord.visibility = View.VISIBLE
                }
            } else {
                imgRecord.visibility = View.GONE
            }

            val isHighlighted = record.id == highlightedId
            card.strokeWidth = if (isHighlighted) (4 * resources.displayMetrics.density).toInt() else 0
            card.strokeColor = if (isHighlighted) getColor(R.color.highlight_accent) else 0
            return view
        }
    }

    private var currentPlayer: MediaPlayer? = null
    private val playbackHandler = Handler(Looper.getMainLooper())
    private var playbackTickRunnable: Runnable? = null

    private fun transcribeAndPlay(record: Knowledge, path: String, txtContext: TextView) {
        val file = File(path)
        if (!file.exists()) return
        playbackTickRunnable?.let { playbackHandler.removeCallbacks(it) }
        if (currentPlayer?.isPlaying == true) {
            currentPlayer?.stop()
            currentPlayer?.release()
            currentPlayer = null
        }
        Toast.makeText(this, "Transcribing...", Toast.LENGTH_SHORT).show()
        thread {
            val transcriber = AudioTranscriber(this)
            transcriber.ensureModel()
            val wordsWithTime = transcriber.transcribeWithWordTimings(file)
            val fullText = transcriber.transcribe(file)
            runOnUiThread {
                val displayText = when {
                    fullText == null -> null
                    fullText.isEmpty() -> "No speech"
                    else -> fullText
                }
                if (displayText != null) {
                    txtContext.text = displayText
                    record.content = displayText
                    if (displayText.isNotEmpty()) {
                        Toast.makeText(this@MainActivity, displayText, Toast.LENGTH_LONG).show()
                        try {
                            val vector = textEmbedder.embed(displayText)
                                .embeddingResult().embeddings().first().floatEmbedding()
                            record.vector = vector
                            knowledgeBox?.put(record)
                        } catch (_: Exception) { }
                    } else {
                        Toast.makeText(this@MainActivity, "No speech detected", Toast.LENGTH_SHORT).show()
                    }
                } else {
                    Toast.makeText(this@MainActivity, "Transcription failed (WAV required)", Toast.LENGTH_LONG).show()
                }
                try {
                    currentPlayer = MediaPlayer().apply {
                        setDataSource(path)
                        prepare()
                        setOnCompletionListener {
                            playbackTickRunnable?.let { playbackHandler.removeCallbacks(it) }
                            txtContext.text = record.content ?: ""
                            currentPlayer = null
                        }
                        start()
                        if (!wordsWithTime.isNullOrEmpty()) {
                            startTranscriptSync(txtContext, wordsWithTime, this)
                        }
                    }
                } catch (e: Exception) {
                    Toast.makeText(this, "Cannot play audio", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun startTranscriptSync(txtContext: TextView, words: List<Pair<String, Float>>, player: MediaPlayer) {
        playbackTickRunnable = object : Runnable {
            override fun run() {
                try {
                    if (!player.isPlaying) return
                    val posSec = player.currentPosition / 1000f
                    val shown = words.takeWhile { it.second <= posSec }.joinToString(" ") { it.first }
                    txtContext.text = shown
                } catch (_: Exception) { return }
                playbackHandler.postDelayed(this, 150)
            }
        }
        playbackHandler.post(playbackTickRunnable!!)
    }

    private fun setupLLM() {
        thread {
            try {
                val options = LlmInference.LlmInferenceOptions.builder()
                    .setModelPath("/data/local/tmp/llm/gemma3-1b-it-int4.task")
                    .setMaxTokens(512)
                    .build()
                llmInference = LlmInference.createFromOptions(this, options)
                isLlmReady = true
                updateStatus()
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this, "LLM Load Fail: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun setupEmbedder() {
        thread {
            try {
                val baseOptions = BaseOptions.builder()
                    .setModelAssetPath("universal_sentence_encoder.tflite")
                    .build()
                val options = TextEmbedder.TextEmbedderOptions.builder()
                    .setBaseOptions(baseOptions)
                    .setL2Normalize(true)
                    .build()
                textEmbedder = TextEmbedder.createFromOptions(this, options)
                isEmbedderReady = true
                updateStatus()
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this, "Embedder Load Fail: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }
    }

    private fun updateStatus() {
        runOnUiThread {
            if (isLlmReady && isEmbedderReady) {
                findViewById<TextView>(R.id.txtResponse).text = "Ready to chat & recall memories ✅"
                refreshMemoryCount()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        loadMemories()
        refreshPendantIndicator()
    }

    override fun onDestroy() {
        (application as GemmaApp).pauseBleForSync()
        playbackTickRunnable?.let { playbackHandler.removeCallbacks(it) }
        currentPlayer?.release()
        currentPlayer = null
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100 && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            (application as GemmaApp).resumeBleAfterSync()
        }
    }
}
