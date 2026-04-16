package com.example.gemmaapp

import java.util.Calendar
import java.util.regex.Pattern

/**
 * Parses user queries for temporal filters.
 * Supports LLM-based extraction (flexible user phrasing) and keyword fallback.
 */
object MemoryQueryParser {

    data class DateRange(val startMs: Long, val endMs: Long)

    data class ParsedQuery(
        val semanticQuery: String,
        val dateRange: DateRange?,
        val filterLabel: String?
    )

    /** Filter keys the LLM can output. Used for mapping response to DateRange. */
    val SUPPORTED_FILTER_KEYS = setOf(
        "TODAY", "YESTERDAY", "DAY_BEFORE_YESTERDAY",
        "LAST_AFTERNOON", "LAST_EVENING", "LAST_NIGHT", "LAST_MORNING",
        "THIS_MORNING", "THIS_AFTERNOON", "THIS_EVENING",
        "LAST_WEEK", "LAST_MONTH", "LAST_2_WEEKS", "NONE"
    )

    /** Normalize LLM response to filter key. LLM may say "TODAY", "The filter is today", etc. */
    fun normalizeFilterFromLlmResponse(response: String?): String? {
        if (response.isNullOrBlank()) return null
        val upper = response.trim().uppercase().replace(" ", "_")
        for (key in SUPPORTED_FILTER_KEYS) {
            if (key == "NONE") continue
            if (upper.contains(key)) return key.lowercase()
        }
        return null
    }

    /** Compute ParsedQuery from an LLM-provided filter key. */
    fun fromFilterKey(filterKey: String?, fullQuery: String, now: Calendar = Calendar.getInstance()): ParsedQuery {
        val key = filterKey?.trim()?.lowercase()?.replace(" ", "_")
        val validKey = when (key) {
            "today" -> "today"
            "yesterday" -> "yesterday"
            "day_before_yesterday" -> "day_before_yesterday"
            "last_afternoon" -> "last_afternoon"
            "last_evening" -> "last_evening"
            "last_night" -> "last_night"
            "last_morning" -> "last_morning"
            "this_morning" -> "today_morning"
            "this_afternoon" -> "today_afternoon"
            "this_evening" -> "today_evening"
            "last_week" -> "last_week"
            "last_month" -> "last_month"
            "last_2_weeks" -> "last_2_weeks"
            else -> null
        }
        val dateRange = validKey?.let { computeDateRange(it, now) }
        val filterLabel = validKey?.let { getFilterLabel(it) }
        return ParsedQuery(
            semanticQuery = fullQuery.trim(),
            dateRange = dateRange,
            filterLabel = filterLabel
        )
    }

    private val temporalPatterns = listOf(
        // Order matters - more specific first
        Pair(Pattern.compile("(?:last|yesterday)\\s+afternoon", Pattern.CASE_INSENSITIVE), "last_afternoon"),
        Pair(Pattern.compile("(?:last|yesterday)\\s+evening", Pattern.CASE_INSENSITIVE), "last_evening"),
        Pair(Pattern.compile("(?:last|yesterday)\\s+night", Pattern.CASE_INSENSITIVE), "last_night"),
        Pair(Pattern.compile("(?:last|yesterday)\\s+morning", Pattern.CASE_INSENSITIVE), "last_morning"),
        Pair(Pattern.compile("this\\s+afternoon", Pattern.CASE_INSENSITIVE), "today_afternoon"),
        Pair(Pattern.compile("this\\s+morning", Pattern.CASE_INSENSITIVE), "today_morning"),
        Pair(Pattern.compile("this\\s+evening", Pattern.CASE_INSENSITIVE), "today_evening"),
        Pair(Pattern.compile("day\\s+before\\s+yesterday", Pattern.CASE_INSENSITIVE), "day_before_yesterday"),
        Pair(Pattern.compile("yesterday", Pattern.CASE_INSENSITIVE), "yesterday"),
        Pair(Pattern.compile("last\\s+week", Pattern.CASE_INSENSITIVE), "last_week"),
        Pair(Pattern.compile("past\\s+week", Pattern.CASE_INSENSITIVE), "last_week"),
        Pair(Pattern.compile("last\\s+month", Pattern.CASE_INSENSITIVE), "last_month"),
        Pair(Pattern.compile("past\\s+month", Pattern.CASE_INSENSITIVE), "last_month"),
        Pair(Pattern.compile("last\\s+2\\s+weeks", Pattern.CASE_INSENSITIVE), "last_2_weeks"),
        Pair(Pattern.compile("today", Pattern.CASE_INSENSITIVE), "today")
    )

    /**
     * Parse the user query to extract temporal filter and semantic part.
     * @param query User's raw prompt
     * @param now Reference calendar (typically now)
     */
    fun parse(query: String, now: Calendar = Calendar.getInstance()): ParsedQuery {
        var semanticQuery = query.trim()
        var matchedFilter: String? = null

        for ((pattern, filterKey) in temporalPatterns) {
            val m = pattern.matcher(semanticQuery)
            if (m.find()) {
                matchedFilter = filterKey
                semanticQuery = m.replaceAll(" ").trim()
                break
            }
        }

        semanticQuery = semanticQuery.replace(Regex("\\s+"), " ").trim()

        val dateRange = matchedFilter?.let { computeDateRange(it, now) }
        val filterLabel = matchedFilter?.let { getFilterLabel(it) }

        return ParsedQuery(
            semanticQuery = semanticQuery.ifEmpty { query.trim() },
            dateRange = dateRange,
            filterLabel = filterLabel
        )
    }

    private fun computeDateRange(filterKey: String, now: Calendar): DateRange {
        val cal = now.clone() as Calendar
        val (start, end) = when (filterKey) {
            "today" -> {
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                Pair(cal.timeInMillis, System.currentTimeMillis())
            }
            "today_morning" -> {
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.set(Calendar.HOUR_OF_DAY, 12)
                Pair(startMs, cal.timeInMillis)
            }
            "today_afternoon" -> {
                cal.set(Calendar.HOUR_OF_DAY, 12)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                Pair(cal.timeInMillis, System.currentTimeMillis())
            }
            "today_evening" -> {
                cal.set(Calendar.HOUR_OF_DAY, 18)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                Pair(cal.timeInMillis, System.currentTimeMillis())
            }
            "yesterday" -> {
                cal.add(Calendar.DAY_OF_YEAR, -1)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.add(Calendar.DAY_OF_YEAR, 1)
                Pair(startMs, cal.timeInMillis)
            }
            "last_morning" -> {
                cal.add(Calendar.DAY_OF_YEAR, -1)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.set(Calendar.HOUR_OF_DAY, 12)
                Pair(startMs, cal.timeInMillis)
            }
            "last_afternoon" -> {
                cal.add(Calendar.DAY_OF_YEAR, -1)
                cal.set(Calendar.HOUR_OF_DAY, 12)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.set(Calendar.HOUR_OF_DAY, 18)
                Pair(startMs, cal.timeInMillis)
            }
            "last_evening", "last_night" -> {
                cal.add(Calendar.DAY_OF_YEAR, -1)
                cal.set(Calendar.HOUR_OF_DAY, 18)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.add(Calendar.DAY_OF_YEAR, 1)
                Pair(startMs, cal.timeInMillis)
            }
            "day_before_yesterday" -> {
                cal.add(Calendar.DAY_OF_YEAR, -2)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.add(Calendar.DAY_OF_YEAR, 2)
                Pair(startMs, cal.timeInMillis)
            }
            "last_week" -> {
                cal.add(Calendar.WEEK_OF_YEAR, -1)
                cal.set(Calendar.DAY_OF_WEEK, cal.firstDayOfWeek)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                cal.add(Calendar.WEEK_OF_YEAR, 1)
                Pair(startMs, cal.timeInMillis)
            }
            "last_2_weeks" -> {
                cal.add(Calendar.WEEK_OF_YEAR, -2)
                cal.set(Calendar.DAY_OF_WEEK, cal.firstDayOfWeek)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                Pair(startMs, System.currentTimeMillis())
            }
            "last_month" -> {
                cal.add(Calendar.MONTH, -1)
                cal.set(Calendar.DAY_OF_MONTH, 1)
                cal.set(Calendar.HOUR_OF_DAY, 0)
                cal.set(Calendar.MINUTE, 0)
                cal.set(Calendar.SECOND, 0)
                cal.set(Calendar.MILLISECOND, 0)
                val startMs = cal.timeInMillis
                Pair(startMs, System.currentTimeMillis())
            }
            else -> return computeDateRange("yesterday", now)
        }
        return DateRange(start, end)
    }

    private fun getFilterLabel(filterKey: String): String = when (filterKey) {
        "today" -> "today"
        "today_morning" -> "this morning"
        "today_afternoon" -> "this afternoon"
        "today_evening" -> "this evening"
        "yesterday" -> "yesterday"
        "last_morning" -> "yesterday morning"
        "last_afternoon" -> "yesterday afternoon"
        "last_evening" -> "yesterday evening"
        "last_night" -> "last night"
        "day_before_yesterday" -> "day before yesterday"
        "last_week" -> "last week"
        "last_2_weeks" -> "last 2 weeks"
        "last_month" -> "last month"
        else -> filterKey
    }

    /**
     * Parse datetime from metadata JSON. Supports:
     * - "YYYY-MM-DD HH:MM:SS" (from Esp32Sync)
     * - "YYYYMMDD_HHMMSS" (raw filename format, if ever stored)
     */
    fun parseDatetimeFromMetadata(metadata: String?): Long? {
        if (metadata.isNullOrEmpty()) return null
        return try {
            val obj = org.json.JSONObject(metadata)
            val dt = obj.optString("datetime").trim().takeIf { it.isNotEmpty() } ?: return null

            // Format A: "2025-02-16 14:30:22" (delimiters: - space :)
            val parts = dt.split(Regex("[-\\s:]")).filter { it.isNotEmpty() }
            if (parts.size < 6) {
                // Format B: "20250216_143022" (raw)
                val rawMatch = Regex("(\\d{4})(\\d{2})(\\d{2})[_-](\\d{2})(\\d{2})(\\d{2})").find(dt)
                if (rawMatch != null) {
                    val (y, mo, d, h, mi, s) = rawMatch.destructured
                    return parseToMillis(
                        y.toInt(), mo.toInt(), d.toInt(),
                        h.toInt(), mi.toInt(), s.toInt()
                    )
                }
                return null
            }
            val year = parts[0].toIntOrNull() ?: return null
            val month = parts[1].toIntOrNull() ?: return null
            val day = parts[2].toIntOrNull() ?: return null
            val hour = parts.getOrNull(3)?.toIntOrNull() ?: 0
            val min = parts.getOrNull(4)?.toIntOrNull() ?: 0
            val sec = parts.getOrNull(5)?.toIntOrNull() ?: 0
            parseToMillis(year, month, day, hour, min, sec)
        } catch (_: Exception) { null }
    }

    private fun parseToMillis(year: Int, month: Int, day: Int, hour: Int, min: Int, sec: Int): Long? {
        if (month !in 1..12 || day !in 1..31) return null
        return try {
            Calendar.getInstance().apply {
                set(Calendar.YEAR, year)
                set(Calendar.MONTH, month - 1)  // Calendar month is 0-based
                set(Calendar.DAY_OF_MONTH, day)
                set(Calendar.HOUR_OF_DAY, hour)
                set(Calendar.MINUTE, min)
                set(Calendar.SECOND, sec)
                set(Calendar.MILLISECOND, 0)
            }.timeInMillis
        } catch (_: Exception) { null }
    }

    /**
     * Get record's capture time in ms. Tries "datetime" in metadata (format "YYYY-MM-DD HH:MM:SS"),
     * then extracts from filename (image_YYYYMMDD_HHMMSS.jpg).
     */
    fun getRecordTimestampMs(record: Knowledge): Long? {
        record.metadata?.let { parseDatetimeFromMetadata(it) }?.let { return it }
        // Fallback: extract from filename in metadata or imagePath (e.g. esp32_xxx_image_20250216_143022.jpg)
        val meta = record.metadata ?: ""
        val filename = try {
            org.json.JSONObject(meta).optString("filename").takeIf { it.isNotEmpty() }
        } catch (_: Exception) { null }
            ?: record.imagePath?.substringAfterLast('/')?.substringAfter("esp32_")?.substringAfter("_")
            ?: return null
        // Filename format: image_20250216_143022.jpg or 20250216_143022.jpg
        val rawMatch = Regex("(\\d{4})(\\d{2})(\\d{2})[_-](\\d{2})(\\d{2})(\\d{2})").find(filename) ?: return null
        val (y, mo, d, h, mi, s) = rawMatch.destructured
        return parseToMillis(y.toInt(), mo.toInt(), d.toInt(), h.toInt(), mi.toInt(), s.toInt())
    }

    fun recordMatchesDateRange(record: Knowledge, range: DateRange): Boolean {
        val ms = getRecordTimestampMs(record) ?: return false
        return ms in range.startMs..range.endMs
    }
}
