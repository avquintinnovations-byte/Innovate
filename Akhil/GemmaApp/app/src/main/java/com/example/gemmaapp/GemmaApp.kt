package com.example.gemmaapp

import android.app.Application
import android.content.SharedPreferences
import io.objectbox.BoxStore

class GemmaApp : Application() {

    var boxStore: BoxStore? = null
        private set

    var bleIndexManager: BleIndexManager? = null
        private set

    private val prefs: SharedPreferences by lazy {
        getSharedPreferences("gemma_prefs", MODE_PRIVATE)
    }

    /** Last pendant index from BLE; persisted so "new memories" shows on app reopen */
    var lastPendantIndex: Int
        get() = prefs.getInt("last_pendant_index", -1)
        set(value) {
            prefs.edit().putInt("last_pendant_index", value).commit()
        }

    fun initBleIndexManager(onIndexReceived: (Int) -> Unit, onConnectionChanged: ((Boolean) -> Unit)? = null) {
        bleIndexManager?.stop()
        bleIndexManager = BleIndexManager(this, { idx ->
            lastPendantIndex = idx
            onIndexReceived(idx)
        }, onConnectionChanged)
        bleIndexManager?.start()
    }

    fun pauseBleForSync() {
        bleIndexManager?.stop()
    }

    fun resumeBleAfterSync() {
        bleIndexManager?.start()
    }

    fun getSyncedEsp32Count(): Int {
        val box = boxStore?.boxFor(Knowledge::class.java) ?: return 0
        return box.query().build().find().count { it.metadata?.contains("\"source\":\"esp32\"") == true }
    }

    override fun onCreate() {
        super.onCreate()
        boxStore = initBoxStore()
    }

    private fun initBoxStore(): BoxStore? {
        return try {
            MyObjectBox.builder().androidContext(this).build()
        } catch (e: Exception) {
            try {
                io.objectbox.BoxStore.deleteAllFiles(this, io.objectbox.BoxStoreBuilder.DEFAULT_NAME)
                MyObjectBox.builder().androidContext(this).build()
            } catch (e2: Exception) {
                null
            }
        }
    }
}
