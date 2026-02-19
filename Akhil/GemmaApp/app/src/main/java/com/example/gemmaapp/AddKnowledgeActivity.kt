package com.example.gemmaapp

import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.text.textembedder.TextEmbedder
import io.objectbox.Box
import kotlin.concurrent.thread
import java.io.File
import java.io.FileOutputStream

class AddKnowledgeActivity : AppCompatActivity() {

    private var knowledgeBox: Box<Knowledge>? = null
    private var textEmbedder: TextEmbedder? = null
    private var selectedImageUri: Uri? = null
    private var savedImagePath: String? = null
    private var cameraOutputFile: File? = null

    private val pickImage = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        uri?.let {
            selectedImageUri = it
            showImage(it)
        }
    }

    private val takePicture = registerForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) {
            cameraOutputFile?.let { file ->
                selectedImageUri = Uri.fromFile(file)
                showImage(selectedImageUri!!)
            }
        } else {
            Toast.makeText(this, "Photo not taken", Toast.LENGTH_SHORT).show()
        }
    }

    private val requestPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) launchCamera() else Toast.makeText(this, "Camera permission required", Toast.LENGTH_LONG).show()
    }

    private fun showImage(uri: Uri) {
        val bitmap = contentResolver.openInputStream(uri)?.use { stream ->
            BitmapFactory.decodeStream(stream)
        }
        findViewById<android.widget.ImageView>(R.id.imgPreview).setImageBitmap(bitmap)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_add_knowledge)

        // Use singleton ObjectBox from Application (no second store = no crash)
        knowledgeBox = (application as GemmaApp).boxStore?.boxFor(Knowledge::class.java)
        if (knowledgeBox == null) {
            Toast.makeText(this, "Database not available", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        findViewById<android.widget.Button>(R.id.btnCamera).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                when {
                    checkSelfPermission(android.Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED -> launchCamera()
                    shouldShowRequestPermissionRationale(android.Manifest.permission.CAMERA) -> requestPermission.launch(android.Manifest.permission.CAMERA)
                    else -> requestPermission.launch(android.Manifest.permission.CAMERA)
                }
            } else {
                launchCamera()
            }
        }

        findViewById<android.widget.Button>(R.id.btnGallery).setOnClickListener {
            pickImage.launch("image/*")
        }

        findViewById<android.widget.Button>(R.id.btnSave).setOnClickListener {
            saveKnowledge()
        }
    }

    private fun launchCamera() {
        val imagesDir = File(cacheDir, "camera").apply { mkdirs() }
        cameraOutputFile = File(imagesDir, "photo_${System.currentTimeMillis()}.jpg")
        val uri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", cameraOutputFile!!)
        takePicture.launch(uri)
    }

    private fun ensureEmbedder(): Boolean {
        if (textEmbedder != null) return true
        return try {
            val baseOptions = BaseOptions.builder()
                .setModelAssetPath("universal_sentence_encoder.tflite")
                .build()
            val options = TextEmbedder.TextEmbedderOptions.builder()
                .setBaseOptions(baseOptions)
                .setL2Normalize(true)
                .build()
            textEmbedder = TextEmbedder.createFromOptions(this, options)
            true
        } catch (e: Exception) {
            Toast.makeText(this, "Embedder failed: ${e.message}", Toast.LENGTH_LONG).show()
            false
        }
    }

    private fun saveKnowledge() {
        val context = findViewById<android.widget.EditText>(R.id.etContext).text.toString().trim()
        if (context.isEmpty()) {
            Toast.makeText(this, "Context is required", Toast.LENGTH_SHORT).show()
            return
        }
        if (!ensureEmbedder()) return

        val metadata = findViewById<android.widget.EditText>(R.id.etMetadata).text.toString().trim()
            .takeIf { it.isNotEmpty() }

        thread {
            try {
                val embedder = textEmbedder ?: throw IllegalStateException("Embedder not ready")
                val vector = embedder.embed(context).embeddingResult().embeddings().first().floatEmbedding()
                savedImagePath = selectedImageUri?.let { uri -> copyImageToAppStorage(uri) }

                val box = knowledgeBox ?: return@thread
                val record = Knowledge(
                    content = context,
                    imagePath = savedImagePath,
                    metadata = metadata,
                    vector = vector
                )
                box.put(record)

                runOnUiThread {
                    Toast.makeText(this@AddKnowledgeActivity, "Memory saved", Toast.LENGTH_SHORT).show()
                    setResult(RESULT_OK)
                    finish()
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this@AddKnowledgeActivity, "Error: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun copyImageToAppStorage(uri: Uri): String {
        val imagesDir = File(filesDir, "knowledge_images").apply { mkdirs() }
        val fileName = "img_${System.currentTimeMillis()}.jpg"
        val destFile = File(imagesDir, fileName)

        when (uri.scheme) {
            "file" -> File(uri.path ?: "").inputStream().use { input ->
                FileOutputStream(destFile).use { output -> input.copyTo(output) }
            }
            else -> contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(destFile).use { output -> input.copyTo(output) }
            }
        }
        return destFile.absolutePath
    }
}
