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
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.UUID

/**
 * BLE manager to receive index value from ESP32-S3 Pendant.
 * Connects to "Memorable" device, subscribes to index characteristic.
 * Stays connected; when ESP32 saves new file, it automatically notifies and we update the display.
 */
class BleIndexManager(
    private val context: Context,
    private val onIndexReceived: (Int) -> Unit,
    private val onConnectionStateChanged: ((Boolean) -> Unit)? = null
) {
    companion object {
        private const val TAG = "BleIndexManager"
        private const val DEVICE_NAME = "Memorable"
        private val SERVICE_UUID = UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
        private val INDEX_CHAR_UUID = UUID.fromString("6e400003-b5a3-f393-e0a9-e50e24dcca9e")
        private const val RECONNECT_DELAY_MS = 3000L
    }

    private val handler = Handler(Looper.getMainLooper())
    private val bluetoothManager: BluetoothManager? =
        context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager?.adapter
    private var leScanner: BluetoothLeScanner? = null
    private var gatt: BluetoothGatt? = null
    private var isScanning = false
    private var targetDevice: BluetoothDevice? = null
    // True between stop() and start(). Prevents the async STATE_DISCONNECTED
    // callback from scheduling a reconnect while a file-transfer sync is running.
    @Volatile private var paused = false

    fun isBluetoothAvailable(): Boolean {
        return bluetoothAdapter != null && bluetoothAdapter.isEnabled
    }

    @SuppressLint("MissingPermission")
    fun start() {
        paused = false  // allow reconnects again
        if (!isBluetoothAvailable()) {
            Log.w(TAG, "Bluetooth not available")
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                Log.w(TAG, "BLUETOOTH_CONNECT permission required")
                return
            }
        } else {
            // Android ≤ 11: BLE scanning requires ACCESS_FINE_LOCATION
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                Log.w(TAG, "ACCESS_FINE_LOCATION required for BLE scanning on Android ≤ 11")
                return
            }
        }
        stop()
        leScanner = bluetoothAdapter?.bluetoothLeScanner
        scanForDevice()
    }

    @SuppressLint("MissingPermission")
    fun stop() {
        // 1. Block any future reconnect attempts (the STATE_DISCONNECTED callback
        //    fires async after close() — it must NOT re-launch a GATT connection
        //    while BleSyncHelper is about to do its own scan+connect.
        paused = true
        handler.removeCallbacksAndMessages(null)
        // 2. Proper disconnect first. close() alone sometimes doesn't send a GATT
        //    disconnect PDU, so the ESP32 keeps thinking it's connected (and stops
        //    advertising) until its supervision timeout fires ~2 s later.
        try { gatt?.disconnect() } catch (_: Exception) { }
        gatt?.close()
        gatt = null
        targetDevice = null
        if (isScanning) {
            leScanner?.stopScan(scanCallback)
            isScanning = false
        }
    }

    @SuppressLint("MissingPermission")
    private fun scanForDevice() {
        if (leScanner == null || isScanning) return
        // Filter by service UUID — reliable on all Android versions including 12+.
        // Device name can be null in scan results when BLUETOOTH_SCAN uses neverForLocation.
        val filter = ScanFilter.Builder()
            .setServiceUuid(android.os.ParcelUuid(SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()
        isScanning = true
        leScanner?.startScan(listOf(filter), settings, scanCallback)
        handler.postDelayed({
            if (isScanning) {
                leScanner?.stopScan(scanCallback)
                isScanning = false
                scanForDevice()
            }
        }, 10000)
    }

    private val scanCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            // Device name may be null when filtered by service UUID — that's fine, accept it.
            val name = result.device.name
            if (name == null || name == DEVICE_NAME) {
                leScanner?.stopScan(this)
                isScanning = false
                targetDevice = result.device
                // Cache MAC so BleSyncHelper can connect directly without scanning —
                // avoids Android's "scanning too frequently" throttle.
                (context.applicationContext as? GemmaApp)?.lastPendantMac = result.device.address
                connectGatt(result.device)
            }
        }

        override fun onScanFailed(errorCode: Int) {
            isScanning = false
            if (!paused) handler.postDelayed({ if (!paused) scanForDevice() }, RECONNECT_DELAY_MS)
        }
    }

    @SuppressLint("MissingPermission")
    private fun connectGatt(device: BluetoothDevice) {
        gatt = device.connectGatt(context, false, gattCallback)
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    gatt.discoverServices()
                    onConnectionStateChanged?.invoke(true)
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    onConnectionStateChanged?.invoke(false)
                    // Don't reconnect if we're paused for a file-transfer sync.
                    if (!paused) {
                        handler.postDelayed({
                            if (!paused) targetDevice?.let { connectGatt(it) }
                        }, RECONNECT_DELAY_MS)
                    }
                }
            }
        }

        @SuppressLint("MissingPermission")
        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) return
            val service = gatt.getService(SERVICE_UUID) ?: return
            val characteristic = service.getCharacteristic(INDEX_CHAR_UUID) ?: return
            gatt.setCharacteristicNotification(characteristic, true)
            val descriptor = characteristic.getDescriptor(
                UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
            )
            descriptor?.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            gatt.writeDescriptor(descriptor)
            gatt.readCharacteristic(characteristic)
        }

        override fun onCharacteristicRead(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                characteristic.value?.let { parseAndNotify(it) }
            }
        }

        override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
            characteristic.value?.let { parseAndNotify(it) }
        }
    }

    private fun parseAndNotify(value: ByteArray) {
        try {
            val str = String(value, Charsets.UTF_8).trim()
            val idx = str.toIntOrNull() ?: return
            handler.post { onIndexReceived(idx) }
        } catch (_: Exception) { }
    }
}
