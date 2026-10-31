package org.idotmatrix.pixelmeteo

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Keeps the display's clock going while the phone sleeps: each minute, the GIF
 * of that whole minute (seconds ticking, places taking turns) is drawn by the
 * Studio's meteo.py and sent over Bluetooth; the forecasts are fetched again
 * every 15 to 60 minutes; the brightness follows the first place's sun.
 */
class MeteoService : Service() {
    companion object {
        private const val CHANNEL = "meteo"
        private const val NOTIFICATION = 1

        fun start(context: Context) {
            val intent = Intent(context, MeteoService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, MeteoService::class.java))
        }

        // A settings change while it runs: the display gets the new screen at once. Conflated:
        // changes made during a send come down to one, the newest, sent right after it.
        private val changes = Channel<Unit>(Channel.CONFLATED)

        fun poke() {
            changes.trySend(Unit)
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null
    private var frame: Frame? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    // Bluetooth switched back on: the frame is tried at once.
    private val bluetooth = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, -1) == BluetoothAdapter.STATE_ON) poke()
        }
    }

    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        registerReceiver(bluetooth, IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED))
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "Heure et météo sur le cadre",
                NotificationManager.IMPORTANCE_LOW))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = notification("Démarrage…")
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION, notification)
        }
        if (wakeLock == null) {
            wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "pixelmeteo:clock").apply { acquire() }
        }
        Store.setRunning(this, true)
        if (loop?.isActive != true) {
            Store.log(this, "service démarré")
            loop = scope.launch { run() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        Store.log(this, "service arrêté")
        unregisterReceiver(bluetooth)
        Store.setRunning(this, false)
        Store.status(this, "Arrêté")
        scope.cancel()
        frame?.close()
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        return builder.setContentTitle("Pixel Météo")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_day)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private fun say(text: String) {
        Store.status(this, text)
        Store.log(this, text)
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification(text))
    }

    private suspend fun run() {
        val py = Python.getInstance().getModule("pixelmeteo")
        var lead = 1.5        // how long the last minute took to arrive
        var fetchedAt = 0L
        var brightness = -1
        val time = SimpleDateFormat("HH:mm", Locale.FRANCE)
        var missed = false  // the frame was not reached: tried again sooner than the next minute
        var sent = ""        // what the last minute sent was made of: the same again in that minute is not resent
        while (scope.isActive) {
            val device = Store.device(this)
            val cfg = Store.config(this)
            if (device == null || cfg == null) {
                say("Choisis un cadre et une ville dans l'appli")
                delay(30_000)
                continue
            }
            val refresh = Store.refreshSeconds(this)
            if (System.currentTimeMillis() - fetchedAt >= refresh * 1000L) {
                try {
                    py.callAttr("refresh", cfg.toString(), refresh.toDouble())
                    fetchedAt = System.currentTimeMillis()
                } catch (e: Exception) {
                    // Asked again in 5 minutes; the last forecast (if any) stays up meanwhile.
                    fetchedAt = System.currentTimeMillis() - (refresh - 300) * 1000L
                    say("Météo injoignable : ${e.message?.lineSequence()?.lastOrNull() ?: e.javaClass.simpleName}")
                }
            }
            val made = "${cfg}|${Store.followed(this)}|${device.address}|${System.currentTimeMillis() / 60_000}"
            if (made == sent && !missed) {  // woken by a change that changed nothing: the frame has it already
                val now = System.currentTimeMillis()
                withTimeoutOrNull(60_000 - now % 60_000 + 200) { changes.receive() }
                continue
            }
            try {
                val f = frame?.takeIf { it.address == device.address } ?: Frame(this, device.address).also {
                    frame?.close()
                    frame = it
                }
                val wanted = py.callAttr("brightness", cfg.toString()).toInt()
                if (wanted >= 0 && wanted != brightness) {
                    f.brightness(wanted)
                    brightness = wanted
                }
                val agenda = Calendars.forView(this, cfg)
                val gif = py.callAttr("minute_gif", cfg.toString(), device.size, lead, agenda, Store.followed(this))
                    .toJava(ByteArray::class.java)
                val started = System.currentTimeMillis()
                f.showGif(gif)
                lead = ((System.currentTimeMillis() - started) / 1000.0).coerceIn(0.5, 10.0)
                say("${device.name} : minute de ${time.format(Date())} envoyée (${"%.1f".format(gif.size / 1024.0)} Ko)")
                missed = false
                sent = made
            } catch (e: Exception) {
                frame?.close()  // out of range, off: tried again in 15 s, connected as soon as it is there
                say("En attente du cadre (${e.message?.lineSequence()?.lastOrNull() ?: e.javaClass.simpleName})")
                missed = true
            }
            // Just after the next minute starts (15 s while the frame is away), or at once when the settings change.
            val now = System.currentTimeMillis()
            val wait = if (missed) 15_000L else 60_000 - now % 60_000 + 200
            if (withTimeoutOrNull(wait) { changes.receive() } != null) {
                delay(400)  // a few changes in a row (a colour being picked...): only the last one
                while (changes.tryReceive().isSuccess) { /* coalesced */ }
            }
        }
    }
}

/** What the app keeps: the display, the weather view, and what the service last did. */
object Store {
    data class Device(val address: String, val name: String, val size: Int)

    private fun prefs(context: Context) = context.getSharedPreferences("pixelmeteo", Context.MODE_PRIVATE)

    fun device(context: Context): Device? {
        val p = prefs(context)
        val address = p.getString("address", null) ?: return null
        return Device(address, p.getString("name", address) ?: address, p.getInt("size", 64))
    }

    fun setDevice(context: Context, address: String, name: String, size: Int) {
        prefs(context).edit().putString("address", address).putString("name", name).putInt("size", size).apply()
    }

    /** The weather view (meteo.py's WEATHER_SCHEMA), null until a place is chosen. */
    fun config(context: Context): JSONObject? = prefs(context).getString("config", null)?.let { JSONObject(it) }

    /** Screens shared from another phone: theirs taken, the notes, birthdays and reminders of both kept. */
    fun importConfig(context: Context, json: String) {
        val incoming = try { JSONObject(json) } catch (e: Exception) { return }
        if (!incoming.has("profiles")) return
        val mine = config(context)
        if (mine != null) {
            for (key in listOf("notes", "birthdays", "reminders")) {
                val merged = org.json.JSONArray()
                val seen = mutableSetOf<String>()
                for (list in listOf(incoming.optJSONArray(key), mine.optJSONArray(key))) {
                    for (i in 0 until (list?.length() ?: 0)) {
                        val item = list!!.get(i)
                        if (seen.add(item.toString())) merged.put(item)
                    }
                }
                incoming.put(key, merged)
            }
            // This phone's own: its calendars (their numbers are the phone's), its contacts.
            for (key in listOf("agenda_device", "contacts_birthdays")) {
                if (mine.has(key)) incoming.put(key, mine.get(key)) else incoming.remove(key)
            }
        }
        prefs(context).edit().putString("config", incoming.toString()).apply()
        setStopped(context, false)
    }

    /** A note shared to the app, added to the view's notes (the newest first). */
    fun addNote(context: Context, text: String) {
        val config = config(context) ?: JSONObject().put("profiles", org.json.JSONArray().put(JSONObject().put("source", "place")))
        val notes = config.optJSONArray("notes") ?: org.json.JSONArray()
        val kept = org.json.JSONArray().put(text)
        for (i in 0 until minOf(notes.length(), 29)) kept.put(notes.getString(i))
        config.put("notes", kept)
        prefs(context).edit().putString("config", config.toString()).apply()
    }

    fun setConfig(context: Context, config: String, refreshSeconds: Int) {
        prefs(context).edit().putString("config", config).putInt("refresh", refreshSeconds).apply()
    }

    fun refreshSeconds(context: Context) = prefs(context).getInt("refresh", 1800)

    fun status(context: Context, text: String) {
        prefs(context).edit().putString("status", text).putLong("status_at", System.currentTimeMillis()).apply()
    }

    fun status(context: Context): String = prefs(context).getString("status", "") ?: ""

    /** The journal: what happened (sends, errors, changes), the last 2000 lines, for the diagnostic. */
    private val stamp = java.text.SimpleDateFormat("MM-dd HH:mm:ss", java.util.Locale.FRANCE)

    @Synchronized
    fun log(context: Context, line: String) {
        val file = java.io.File(context.filesDir, "journal.txt")
        file.appendText("${stamp.format(java.util.Date())}  $line\n")
        if (file.length() > 300_000) file.writeText(file.readLines().takeLast(2000).joinToString("\n", postfix = "\n"))
    }

    fun journal(context: Context): String =
        java.io.File(context.filesDir, "journal.txt").takeIf { it.exists() }?.readText() ?: "(vide)"

    fun running(context: Context) = prefs(context).getBoolean("running", false)

    /** The screen the app is on while « Suivre l'écran du téléphone » is on and the app open (-1: all in turn). */
    fun followed(context: Context) = prefs(context).getInt("followed", -1)

    fun follow(context: Context, screen: Int) {
        prefs(context).edit().putInt("followed", screen).apply()
    }

    /** « Arrêter » pressed: the frame stays free (no start at boot) until the next change. */
    fun stopped(context: Context) = prefs(context).getBoolean("stopped", false)

    fun setStopped(context: Context, stopped: Boolean) {
        prefs(context).edit().putBoolean("stopped", stopped).apply()
    }

    fun setRunning(context: Context, running: Boolean) {
        prefs(context).edit().putBoolean("running", running).apply()
    }
}
