package org.idotmatrix.pixelmeteo

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.Html
import android.util.Log
import android.view.KeyEvent
import android.view.WindowInsets
import android.webkit.ConsoleMessage
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import kotlin.concurrent.thread

/** Pixel Studio's page: the Studio the service runs (StudioService), as on the PC and the Pi. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private var choosing: ValueCallback<Array<Uri>>? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.webViewClient = WebViewClient()  // the Studio's links stay in the app
        web.webChromeClient = object : WebChromeClient() {
            // The page's errors in Android's log (adb logcat -s PixelStudio).
            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                Log.d("PixelStudio", "${message.message()} (ligne ${message.lineNumber()})")
                return true
            }

            // The Studio's « Ajouter » (images, GIF): the phone's file picker.
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                choosing?.onReceiveValue(null)
                choosing = callback
                return try {
                    startActivityForResult(params.createIntent(), PICK)
                    true
                } catch (e: Exception) {
                    choosing = null
                    false
                }
            }
        }
        waiting("Démarrage du Studio…")
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
        StudioService.start(this)
        StudioService.whenReady { url, error ->
            runOnUiThread {
                if (url != null) web.loadUrl(url)
                else waiting("Le Studio n'a pas démarré : $error")
            }
        }
        shared(intent)
    }

    private fun waiting(text: String) {
        web.loadDataWithBaseURL(null, "<body style='background:#111418;color:#ccc;font:16px sans-serif;" +
            "display:flex;align-items:center;justify-content:center;height:90vh;text-align:center'>" +
            Html.escapeHtml(text) + "</body>", "text/html", "utf-8", null)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared(intent)
    }

    /** A text shared to the app (a Keep note...): a note on the weather view showing. */
    private fun shared(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim()?.takeIf { it.isNotEmpty() } ?: return
        intent.action = null
        StudioService.whenReady { url, _ ->
            if (url != null) thread {
                val said = try {
                    "Note ajoutée à « ${StudioService.py("add_note", text)} »"
                } catch (e: Exception) {
                    e.message?.lineSequence()?.lastOrNull()?.substringAfter(": ") ?: "Note pas ajoutée"
                }
                runOnUiThread {
                    Toast.makeText(this, said, Toast.LENGTH_LONG).show()
                    web.reload()
                }
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == PICK) {
            choosing?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            choosing = null
            return
        }
        super.onActivityResult(requestCode, resultCode, data)
    }

    // The phone's back button goes back in the Studio first.
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        batteryFree()
    }

    private fun askPermissions() {
        val wanted = mutableListOf(Manifest.permission.READ_CALENDAR, Manifest.permission.READ_CONTACTS)
        if (Build.VERSION.SDK_INT >= 31) {
            wanted += listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            wanted += Manifest.permission.ACCESS_FINE_LOCATION
        }
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1) else batteryFree()
    }

    /** Once: let the routines run while the phone sleeps (Android otherwise slows the app down). */
    @SuppressLint("BatteryLife")
    private fun batteryFree() {
        val prefs = getSharedPreferences("studio", Context.MODE_PRIVATE)
        if (prefs.getBoolean("battery_asked", false)) return
        prefs.edit().putBoolean("battery_asked", true).apply()
        if (getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)) return
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (e: Exception) {
            Log.w("PixelStudio", "battery", e)
        }
    }

    companion object {
        private const val PICK = 7
    }
}
