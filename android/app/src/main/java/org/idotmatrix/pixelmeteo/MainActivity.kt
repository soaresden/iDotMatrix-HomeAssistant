package org.idotmatrix.pixelmeteo

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.widget.FrameLayout
import android.view.WindowInsets
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

// What marks a configuration shared from another phone (the rest is the view's JSON).
const val SHARE_MARK = "PIXELMETEO:"

/** The settings page (assets/index.html) and its bridge to the Bluetooth, Python and the service. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.addJavascriptInterface(Bridge(), "Android")
        // The page's errors in Android's log (adb logcat -s PixelMeteo).
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                Log.d("PixelMeteo", "${message.message()} (ligne ${message.lineNumber()})")
                return true
            }
        }
        web.loadUrl("file:///android_asset/index.html")
        // Android 15 draws apps under the status and navigation bars: the page goes between them.
        val frame = FrameLayout(this)
        frame.setBackgroundColor(0xFF111418.toInt())
        frame.addView(web)
        frame.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(frame)
        askPermissions()
        shared(intent)
        if (!Store.stopped(this)) show()  // what was set up shows on the frame at once, no button to press
    }

    /** The frame shows the view (the service starts, or takes the change at once if it runs). */
    private fun show() {
        if (Store.device(this) == null || Store.config(this) == null) return
        Store.setStopped(this, false)
        MeteoService.start(this)
        MeteoService.poke()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (shared(intent)) web.reload()  // the note or the screens received, shown
    }

    /** A text shared to the app (a Keep note...): a new note on the display's notes. */
    private fun shared(intent: Intent?): Boolean {
        if (intent?.action != Intent.ACTION_SEND) return false
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val at = text.indexOf(SHARE_MARK)
        if (at >= 0) {  // screens shared from another phone: taken, the notes added to ours
            Store.importConfig(this, text.substring(at + SHARE_MARK.length).trim())
            MeteoService.poke()
            intent.action = null
            return true
        }
        Store.addNote(this, text.take(200))
        MeteoService.poke()
        intent.action = null
        return true
    }

    // « Suivre l'écran du téléphone »: only while the app is in front; leaving it, the screens take turns again.
    private var following = -1

    override fun onStart() {
        super.onStart()
        if (following >= 0) {
            Store.follow(this, following)
            MeteoService.poke()
        }
    }

    override fun onStop() {
        if (Store.followed(this) >= 0) {
            Store.follow(this, -1)
            MeteoService.poke()
        }
        super.onStop()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun askPermissions() {
        val wanted = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 31) {
            wanted += listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            wanted += Manifest.permission.ACCESS_FINE_LOCATION
        }
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    /** Answers a call from the page: window.reply(id, ok, json). */
    private fun reply(id: Int, work: suspend () -> String) {
        scope.launch {
            val (ok, result) = try {
                true to withContext(Dispatchers.IO) { work() }
            } catch (e: Exception) {
                false to JSONObject.quote(e.message?.lineSequence()?.lastOrNull()?.substringAfter(": ")
                    ?: e.javaClass.simpleName)
            }
            web.evaluateJavascript("window.reply($id, $ok, $result)", null)
        }
    }

    private val py get() = Python.getInstance().getModule("pixelmeteo")

    inner class Bridge {
        @JavascriptInterface
        fun state(): String {
            val device = Store.device(this@MainActivity)
            val power = getSystemService(PowerManager::class.java)
            return JSONObject()
                .put("device", device?.let { JSONObject().put("address", it.address).put("name", it.name).put("size", it.size) })
                .put("config", Store.config(this@MainActivity))
                .put("refresh", Store.refreshSeconds(this@MainActivity))
                .put("running", Store.running(this@MainActivity))
                .put("status", Store.status(this@MainActivity))
                .put("battery_free", power.isIgnoringBatteryOptimizations(packageName))
                .toString()
        }

        @JavascriptInterface
        fun scan(id: Int) = reply(id) {
            askPermissionsOnMain()
            val found = Frame.scan(this@MainActivity)
            JSONArray(found.map { (address, name) -> JSONObject().put("address", address).put("name", name) }).toString()
        }

        @JavascriptInterface
        fun choose(address: String, name: String, size: Int) {
            Store.setDevice(this@MainActivity, address, name, size)
            runOnUiThread { show() }
        }

        @JavascriptInterface
        fun save(config: String, refresh: Int) {
            Store.setConfig(this@MainActivity, config, refresh)
            Store.log(this@MainActivity, "réglages changés (${config.length} caractères)")
            runOnUiThread { show() }  // live: the display shows the change without pressing anything
        }

        @JavascriptInterface
        fun geocode(id: Int, query: String) = reply(id) { py.callAttr("geocode", query).toString() }

        @JavascriptInterface
        fun preview(id: Int, config: String, size: Int, maxAge: Int, minute: Boolean, page: Int) = reply(id) {
            val agenda = Calendars.forView(this@MainActivity, JSONObject(config))
            py.callAttr("preview", config, size, maxAge.toDouble(), minute, agenda, page).toString()
        }

        /** A zip of everything (settings, state, calendars, engine, journal, log), shared: to find what goes wrong. */
        @JavascriptInterface
        fun exportDiagnostic(id: Int) = reply(id) {
            val (uri, name) = Diagnostic.export(this@MainActivity)
            Store.log(this@MainActivity, "diagnostic exporté : $name")
            withContext(Dispatchers.Main) {
                startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("application/zip")
                    .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "Envoyer le diagnostic"))
            }
            JSONObject().put("name", name).toString()
        }

        /** Everything set up (screens, cities, notes, lists), shared to another phone through any app. */
        @JavascriptInterface
        fun shareConfig() = runOnUiThread {
            val config = Store.config(this@MainActivity) ?: return@runOnUiThread
            val text = "Mes écrans Pixel Météo : ouvre ce message avec Partager → Pixel Météo.\n$SHARE_MARK$config"
            startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, text), "Partager mes écrans"))
        }

        /** The contacts' birthdays: how many (asks for the contacts permission first). */
        @JavascriptInterface
        fun contacts(id: Int) = reply(id) {
            if (!Calendars.contactsAllowed(this@MainActivity)) {
                withContext(Dispatchers.Main) { requestPermissions(arrayOf(Manifest.permission.READ_CONTACTS), 3) }
                throw IllegalStateException("Autorise l'accès aux contacts, puis touche encore le bouton")
            }
            Calendars.birthdays(this@MainActivity).length().toString()
        }

        /** A calendar the phone does not sync: switched on (asks for the permission to edit calendars first). */
        @JavascriptInterface
        fun enableCalendar(id: Int, calendar: String) = reply(id) {
            if (!Calendars.writeAllowed(this@MainActivity)) {
                withContext(Dispatchers.Main) { requestPermissions(arrayOf(Manifest.permission.WRITE_CALENDAR), 4) }
                throw IllegalStateException("Autorise « Agenda » (modifier), puis touche encore « Activer »")
            }
            Calendars.enable(this@MainActivity, calendar)
            Store.log(this@MainActivity, "agenda $calendar activé sur le téléphone (synchro + visible)")
            "true"
        }

        /** The calendars' accounts synced now (then the list is read again). */
        @JavascriptInterface
        fun syncCalendars(id: Int) = reply(id) {
            val asked = Calendars.syncNow(this@MainActivity)
            Store.log(this@MainActivity, "synchronisation des agendas demandée ($asked comptes)")
            asked.toString()
        }

        /** The phone's calendars to pick from (asks for the calendar permission first). */
        @JavascriptInterface
        fun calendars(id: Int) = reply(id) {
            if (!Calendars.allowed(this@MainActivity)) {
                withContext(Dispatchers.Main) { requestPermissions(arrayOf(Manifest.permission.READ_CALENDAR), 2) }
                throw IllegalStateException("Autorise l'accès à l'agenda, puis touche encore « Choisir les agendas »")
            }
            Calendars.list(this@MainActivity).toString()
        }

        @JavascriptInterface
        fun start() = runOnUiThread { MeteoService.start(this@MainActivity) }

        /** The frame shows this screen (-1: the screens take turns again). */
        @JavascriptInterface
        fun follow(screen: Int) = runOnUiThread {
            following = screen
            if (Store.followed(this@MainActivity) != screen) {
                Store.follow(this@MainActivity, screen)
                MeteoService.poke()
            }
        }

        @JavascriptInterface
        fun stop() = runOnUiThread {
            Store.setStopped(this@MainActivity, true)
            MeteoService.stop(this@MainActivity)
        }

        /** Let the clock run while the phone sleeps (Android otherwise slows the app down). */
        @SuppressLint("BatteryLife")
        @JavascriptInterface
        fun batteryFree() = runOnUiThread {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        }
    }

    private suspend fun askPermissionsOnMain() = withContext(Dispatchers.Main) { askPermissions() }
}
