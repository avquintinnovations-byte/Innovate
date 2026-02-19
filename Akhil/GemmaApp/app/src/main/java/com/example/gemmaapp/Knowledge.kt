package com.example.gemmaapp

import io.objectbox.annotation.Entity
import io.objectbox.annotation.HnswIndex
import io.objectbox.annotation.Id
import io.objectbox.annotation.VectorDistanceType

/**
 * Entity storing context, image path, metadata for RAG retrieval.
 * Vector embedding enables semantic search via ObjectBox HNSW index.
 */
@Entity
data class Knowledge(
    @Id var id: Long = 0,
    /** Text context used for RAG - embedded for semantic search */
    var content: String? = null,
    /** Local file path to the linked image (stored in app's files dir) */
    var imagePath: String? = null,
    /** Local file path to linked audio (for ESP32 voice memos, etc.) */
    var audioPath: String? = null,
    /** Additional metadata as JSON string, e.g. {"title":"...","date":"...","tags":[...]} */
    var metadata: String? = null,
    /** Embedding vector from TextEmbedder (768 dims for BERT, or 512 for universal_sentence_encoder) */
    @HnswIndex(dimensions = 768, distanceType = VectorDistanceType.COSINE) var vector: FloatArray? = null
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as Knowledge
        if (id != other.id) return false
        if (content != other.content) return false
        if (imagePath != other.imagePath) return false
        if (audioPath != other.audioPath) return false
        if (metadata != other.metadata) return false
        if (vector != null) {
            if (other.vector == null) return false
            if (!vector!!.contentEquals(other.vector!!)) return false
        } else if (other.vector != null) return false
        return true
    }

    override fun hashCode(): Int {
        var result = id.hashCode()
        result = 31 * result + (content?.hashCode() ?: 0)
        result = 31 * result + (imagePath?.hashCode() ?: 0)
        result = 31 * result + (audioPath?.hashCode() ?: 0)
        result = 31 * result + (metadata?.hashCode() ?: 0)
        result = 31 * result + (vector?.contentHashCode() ?: 0)
        return result
    }
}
