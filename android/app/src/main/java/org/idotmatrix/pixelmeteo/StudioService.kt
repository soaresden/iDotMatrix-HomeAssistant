package org.idotmatrix.pixelmeteo

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import kotlin.concurrent.thread

/**
 * Pixel Studio's server (python/studio_android.py: the PC app's, with the integration's
 * Studio) in a foreground service. It keeps running with the app closed, as Home Assistant
 * does on the Pi: routines, the weather minute, the planning. The app's page shows it.
 */
class StudioService : Service() {
    companion object {
        private const val CHANNEL = "studio"
        private const val NOTIFICATION = 1
        private const val TAG = "PixelStudio"
        // The notification's button: the display's screen off, or on again.
        const val ACTION_SCREEN = "org.idotmatrix.pixelmeteo.SCREEN"

        @Volatile
        var url: String? = null
            private set

        @Volatile
        var error: String? = null
            private set

        private val waiting = mutableListOf<(String?, String?) -> Unit>()

        fun start(context: Context, action: String? = null) {
            val intent = Intent(context, StudioService::class.java).setAction(action)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent) else context.startService(intent)
        }

        /** [callback] with (address, error) once the server answers: at once if it already does. */
        @Synchronized
        fun whenReady(callback: (String?, String?) -> Unit) {
            if (url != null || error != null) callback(url, error) else waiting += callback
        }

        @Synchronized
        private fun ready(address: String?, problem: String?) {
            url = address
            error = problem
            waiting.forEach { it(address, problem) }
            waiting.clear()
        }

        /** studio_android.<function>(args), from a background thread. */
        fun py(function: String, vararg args: Any?) =
            Python.getInstance().getModule("studio_android").callAttr(function, *args)
    }

    private var server: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    @Volatile private var screenOn = true
    @Volatile private var text = "Démarrage du Studio…"
    // What the notification's button could not do, and until when it says so.
    @Volatile private var problem: Pair<String, Long>? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        Ble.context = applicationContext
        Phone.context = applicationContext
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL, "Pixel Studio sur le cadre", NotificationManager.IMPORTANCE_LOW))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION, notification())
        }
        if (wakeLock == null) {  // the routines' timers keep running while the phone sleeps
            wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "pixelstudio:server").apply { acquire() }
        }
        if (server == null) server = thread(name = "studio-start") { run() }
        if (intent?.action == ACTION_SCREEN) {
            val on = !screenOn
            whenReady { address, _ ->
                if (address != null) thread {
                    try {
                        py("screen", on)
                        problem = null
                        refresh()
                    } catch (e: Exception) {  // the frame away...: said for a while in the notification
                        Log.w(TAG, "screen", e)
                        problem = (e.message?.lineSequence()?.lastOrNull()?.substringAfter(": ") ?: "Écran pas changé") to
                            System.currentTimeMillis() + 120_000
                        refresh()
                    }
                }
            }
        }
        return START_STICKY
    }

    private fun run() {
        try {
            val data = File(filesDir, "studio").path
            val media = File(getExternalFilesDir(null) ?: filesDir, "Pixel Studio").path
            ready(py("start", data, media).toString(), null)
        } catch (e: Exception) {
            Log.e(TAG, "start", e)
            ready(null, e.message?.lineSequence()?.lastOrNull() ?: e.javaClass.simpleName)
            text = "Le Studio n'a pas démarré : ouvre l'appli"
            update()
            return
        }
        bringOver()
        while (true) {  // the notification says what the display shows
            refresh()
            Thread.sleep(30_000)
        }
    }

    /** Pixel Météo's view and display (before the Studio), brought over once. */
    private fun bringOver() {
        val old = getSharedPreferences("pixelmeteo", Context.MODE_PRIVATE)
        val config = old.getString("config", null) ?: ""
        val address = old.getString("address", null)
        val device = if (address == null) "" else JSONObject().put("address", address)
            .put("name", old.getString("name", address)).put("size", old.getInt("size", 64)).toString()
        if (config.isEmpty() && device.isEmpty()) return
        try {
            Log.i(TAG, "Pixel Météo repris : " + py("bring_over", config, device, old.getInt("refresh", 1800)))
        } catch (e: Exception) {
            Log.w(TAG, "bring_over", e)
        }
    }

    private fun refresh() {
        try {
            val st = JSONObject(py("status").toString())
            screenOn = st.optBoolean("screen_on", true)
            val display = st.optString("display").takeIf { st.has("display") && !st.isNull("display") }
            val routine = st.optString("routine").takeIf { st.has("routine") && !st.isNull("routine") }
            text = when {
                st.has("error") -> st.getString("error")
                display == null -> "Choisis le cadre dans l'appli"
                !screenOn -> "$display : écran éteint"
                routine != null -> "$routine sur $display"
                st.optBoolean("connected") -> "$display connecté"
                else -> "$display : en attente du cadre"
            }
        } catch (e: Exception) {
            text = e.message ?: "?"
        }
        problem?.let { (said, until) -> if (System.currentTimeMillis() < until) text = said else problem = null }
        update()
    }

    private fun update() {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION, notification())
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val intent = Intent(this, StudioService::class.java).setAction(ACTION_SCREEN)
        val screen = if (Build.VERSION.SDK_INT >= 26) PendingIntent.getForegroundService(this, 1, intent, PendingIntent.FLAG_IMMUTABLE)
        else PendingIntent.getService(this, 1, intent, PendingIntent.FLAG_IMMUTABLE)
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        return builder.setContentTitle("Pixel Studio")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_gallery)
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_lock_power_off, if (screenOn) "Éteindre l'écran" else "Allumer l'écran", screen)
            .build()
    }

    override fun onDestroy() {
        wakeLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}
