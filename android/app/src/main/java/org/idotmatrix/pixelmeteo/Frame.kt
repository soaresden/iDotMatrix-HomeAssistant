package org.idotmatrix.pixelmeteo

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
import android.bluetooth.le.ScanResult
import android.content.Context
import android.os.Build
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import java.util.zip.CRC32

/**
 * One iDotMatrix display over Bluetooth LE, as the integration's client does it
 * (client/connectionManager.py, client/modules/gif.py): a GIF goes in 4 KB
 * packets, each with a 16-byte header, written in 509-byte writes without
 * response; the next packet only goes once the display asks for it.
 */
@SuppressLint("MissingPermission")  // asked for by MainActivity before anything runs
class Frame(private val context: Context, val address: String) {
    companion object {
        val WRITE: UUID = UUID.fromString("0000fa02-0000-1000-8000-00805f9b34fb")
        val NOTIFY: UUID = UUID.fromString("0000fa03-0000-1000-8000-00805f9b34fb")
        val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        const val PACKET = 4096
        const val WRITE_SIZE = 509
        // The display's answers to a packet (its 5th byte).
        const val INVALID = 0
        const val NEXT = 1
        const val NO_SPACE = 2
        const val DONE = 3

        /** Displays nearby (name starting with IDM-), for [seconds]. */
        suspend fun scan(context: Context, seconds: Long = 6): List<Pair<String, String>> {
            val adapter = (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
                ?: throw FrameError("Pas de Bluetooth sur ce téléphone")
            if (!adapter.isEnabled) throw FrameError("Active le Bluetooth")
            val scanner = adapter.bluetoothLeScanner ?: throw FrameError("Active le Bluetooth")
            val found = linkedMapOf<String, String>()
            val callback = object : ScanCallback() {
                override fun onScanResult(callbackType: Int, result: ScanResult) {
                    val name = result.scanRecord?.deviceName ?: result.device.name ?: return
                    if (name.startsWith("IDM-")) found[result.device.address] = name
                }
            }
            scanner.startScan(callback)
            try {
                delay(seconds * 1000)
            } finally {
                scanner.stopScan(callback)
            }
            return found.map { (address, name) -> address to name }
        }
    }

    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private var discoveries = 0
    private var gatt: BluetoothGatt? = null
    private var write: BluetoothGattCharacteristic? = null
    private var writeSize = 20
    private var connected: CompletableDeferred<Unit>? = null
    private var written: CompletableDeferred<Int>? = null
    private val replies = Channel<ByteArray>(Channel.UNLIMITED)
    // Unknown after connecting: the first GIF clears a carousel the display may still run.
    private var carouselMaybe = true
    val isConnected get() = gatt != null && write != null

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                // Larger writes when the phone agrees; discovery follows in onMtuChanged.
                if (!g.requestMtu(517)) g.discoverServices()
            } else {
                connected?.completeExceptionally(FrameError("Le cadre ne répond pas (Bluetooth $status)"))
                written?.completeExceptionally(FrameError("Connexion perdue"))
                close()
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            writeSize = if (status == BluetoothGatt.GATT_SUCCESS) minOf(WRITE_SIZE, mtu - 3) else 20
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            // Looked for in every service, as the integration does: the frames
            // put them in the 16-bit service 0x00FA, not in "fa00".
            val w = g.services.firstNotNullOfOrNull { it.getCharacteristic(WRITE) }
            val n = g.services.firstNotNullOfOrNull { it.getCharacteristic(NOTIFY) }
            if (w == null || n == null) {
                if (discoveries < 3) {
                    // Android may answer from a stale cache (the frame was paired or
                    // used by another app): forget it and discover again.
                    discoveries++
                    refreshCache(g)
                    handler.postDelayed({ g.discoverServices() }, 800L * discoveries)
                    return
                }
                val found = g.services.joinToString { it.uuid.toString().take(8) }.ifEmpty { "aucun" }
                connected?.completeExceptionally(FrameError(
                    "Ce n'est pas un cadre iDotMatrix (statut $status, services trouvés : $found)"))
                return
            }
            write = w
            g.setCharacteristicNotification(n, true)
            val descriptor = n.getDescriptor(CCCD)
            if (descriptor == null) {
                connected?.complete(Unit)
                return
            }
            if (Build.VERSION.SDK_INT >= 33) {
                g.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
            } else {
                @Suppress("DEPRECATION")
                descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                @Suppress("DEPRECATION")
                g.writeDescriptor(descriptor)
            }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            connected?.complete(Unit)
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            written?.complete(status)
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            if (c.uuid == NOTIFY) replies.trySend(value)
        }

        @Deprecated("Android 12 and older")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            if (c.uuid == NOTIFY) replies.trySend(c.value ?: return)
        }
    }

    suspend fun connect() {
        if (isConnected) return
        close()
        val adapter = (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
        if (adapter == null || !adapter.isEnabled) throw FrameError("Active le Bluetooth")
        val device: BluetoothDevice = adapter.getRemoteDevice(address)
        val ready = CompletableDeferred<Unit>()
        connected = ready
        discoveries = 0
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        try {
            withTimeout(20_000) { ready.await() }
        } catch (e: Exception) {
            close()
            throw if (e is FrameError) e else FrameError(
                "Le cadre ne répond pas : allume-le, approche le téléphone et ferme l'appli iDotMatrix")
        }
    }

    /** BluetoothGatt.refresh(), hidden but long-standing: drops Android's cached services. */
    private fun refreshCache(g: BluetoothGatt) {
        try {
            g.javaClass.getMethod("refresh").invoke(g)
        } catch (_: Exception) {
        }
    }

    fun close() {
        try {
            gatt?.disconnect()
            gatt?.close()
        } catch (_: Exception) {
        }
        gatt = null
        write = null
        carouselMaybe = true
    }

    /** One write of at most [writeSize] bytes, waiting for Android to take it. */
    private suspend fun writeOnce(data: ByteArray, response: Boolean) {
        val g = gatt ?: throw FrameError("Cadre déconnecté")
        val c = write ?: throw FrameError("Cadre déconnecté")
        val type = if (response) BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        else BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        repeat(50) {  // the stack may be busy for a moment
            val done = CompletableDeferred<Int>()
            written = done
            val started = if (Build.VERSION.SDK_INT >= 33) {
                g.writeCharacteristic(c, data, type) == BluetoothGatt.GATT_SUCCESS
            } else {
                @Suppress("DEPRECATION")
                c.writeType = type
                @Suppress("DEPRECATION")
                c.value = data
                @Suppress("DEPRECATION")
                g.writeCharacteristic(c)
            }
            if (started) {
                val status = withTimeoutOrNull(5_000) { done.await() } ?: throw FrameError("Écriture Bluetooth bloquée")
                if (status != BluetoothGatt.GATT_SUCCESS) throw FrameError("Écriture Bluetooth refusée ($status)")
                return
            }
            delay(20)
        }
        throw FrameError("Bluetooth occupé")
    }

    private suspend fun send(data: ByteArray, response: Boolean) {
        var i = 0
        while (i < data.size) {
            writeOnce(data.copyOfRange(i, minOf(data.size, i + writeSize)), response)
            i += writeSize
        }
    }

    /** A command (brightness, reset...), acknowledged write. */
    suspend fun command(bytes: ByteArray) {
        connect()
        send(bytes, true)
    }

    suspend fun brightness(percent: Int) = command(byteArrayOf(5, 0, 4, 0x80.toByte(), percent.coerceIn(5, 100).toByte()))

    /** The 4 KB packets of a GIF shown on its own (index 0x0d), as gif.py's _createPayloads. */
    private fun packets(gif: ByteArray): List<ByteArray> {
        val crc = CRC32().apply { update(gif) }.value
        val header = ByteArray(16)
        header[2] = 1  // a GIF
        for (k in 0 until 4) header[5 + k] = (gif.size shr (8 * k)).toByte()
        for (k in 0 until 4) header[9 + k] = (crc shr (8 * k)).toByte()
        header[13] = 5  // carousel interval (unused for a single GIF)
        header[15] = 0x0d
        return (gif.indices step PACKET).mapIndexed { n, start ->
            val chunk = gif.copyOfRange(start, minOf(gif.size, start + PACKET))
            val h = header.copyOf()
            h[4] = if (n > 0) 2 else 0
            val length = chunk.size + 16
            h[0] = length.toByte()
            h[1] = (length shr 8).toByte()
            h + chunk
        }
    }

    /** Send a GIF: fast writes first, acknowledged ones if the display lost some. */
    suspend fun showGif(gif: ByteArray) {
        connect()
        if (carouselMaybe) {
            send(byteArrayOf(4, 0, 3, 0x80.toByte()), true)
            send(byteArrayOf(5, 0, 4, 0x80.toByte(), 0x50), true)
            delay(600)
            carouselMaybe = false
        }
        val all = packets(gif)
        for (fast in listOf(true, true, false)) {
            if (sendPackets(all, fast)) return
            delay(500)
        }
        throw FrameError("Le cadre n'a pas confirmé l'image")
    }

    private suspend fun sendPackets(all: List<ByteArray>, fast: Boolean): Boolean {
        for ((n, packet) in all.withIndex()) {
            while (replies.tryReceive().isSuccess) { /* old answers */ }
            send(packet, !fast)
            val status = withTimeoutOrNull(5_000) {
                var reply: ByteArray
                do {
                    reply = replies.receive()
                } while (!(reply.size >= 5 && reply[1].toInt() == 0 && reply[3].toInt() == 0))
                reply[4].toInt()
            } ?: return false  // no answer: send the file again
            when (status) {
                DONE -> return true
                NEXT -> continue
                NO_SPACE -> throw FrameError("Plus de place sur le cadre pour cette image")
                INVALID -> if (fast) return false else throw FrameError("Le cadre a refusé l'image")
            }
            if (n == all.size - 1) return true
        }
        return true
    }
}

class FrameError(message: String) : Exception(message)

fun bluetoothAdapter(context: Context): BluetoothAdapter? =
    (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
