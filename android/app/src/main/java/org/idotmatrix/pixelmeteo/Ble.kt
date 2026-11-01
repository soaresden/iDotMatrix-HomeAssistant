package org.idotmatrix.pixelmeteo

import android.content.Context
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject

/**
 * Bluetooth for the Studio's Python: what python/bleak (the stand-in for the
 * bleak library) calls, one blocking call at a time from a Python thread.
 * One [Frame] per display address.
 */
object Ble {
    lateinit var context: Context
    private val frames = mutableMapOf<String, Frame>()

    @Synchronized
    private fun frame(address: String) = frames.getOrPut(address) { Frame(context, address) }

    /** Displays nearby: [{"address", "name"}] as JSON. */
    @JvmStatic
    fun scan(seconds: Double): String = runBlocking {
        JSONArray(Frame.scan(context, seconds).map { (address, name) ->
            JSONObject().put("address", address).put("name", name)
        }).toString()
    }

    /** Connects (if not already); returns the size of one write. */
    @JvmStatic
    fun connect(address: String): Int = runBlocking {
        val f = frame(address)
        f.connect()
        f.writeLength
    }

    @JvmStatic
    fun connected(address: String): Boolean = frames[address]?.isConnected == true

    @JvmStatic
    fun write(address: String, data: ByteArray, response: Boolean) = runBlocking {
        frame(address).writeRaw(data, response)
    }

    /** The display's next answer, or null after [ms]. */
    @JvmStatic
    fun reply(address: String, ms: Int): ByteArray? = runBlocking { frame(address).nextReply(ms.toLong()) }

    @JvmStatic
    fun dropReplies(address: String) = frame(address).dropReplies()

    @JvmStatic
    fun forgetServices(address: String) = frame(address).forgetServices()

    @JvmStatic
    fun disconnect(address: String) {
        frames[address]?.close()
    }
}
