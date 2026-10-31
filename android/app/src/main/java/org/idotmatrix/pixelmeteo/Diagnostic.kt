package org.idotmatrix.pixelmeteo

import android.Manifest
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.CalendarContract
import android.provider.MediaStore
import android.util.Base64
import com.chaquo.python.Python
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Everything about the app in one zip (to understand what goes wrong): the settings, the app's state,
 *  the phone's calendars and today's events, what the engine makes of them, the journal and the log. */
object Diagnostic {
    /** Writes the zip to Downloads; returns its address (to share) and its name. */
    fun export(context: Context): Pair<Uri, String> {
        val name = "pixelmeteo-diagnostic-${SimpleDateFormat("yyyy-MM-dd-HHmm", Locale.FRANCE).format(Date())}.zip"
        val bytes = ByteArrayOutputStream()
        ZipOutputStream(bytes).use { zip ->
            fun put(path: String, data: ByteArray) {
                zip.putNextEntry(ZipEntry(path))
                zip.write(data)
                zip.closeEntry()
            }
            fun text(path: String, block: () -> String) {
                val content = try { block() } catch (e: Throwable) { "ERREUR : ${e.stackTraceToString()}" }
                put(path, content.toByteArray())
            }
            val config = Store.config(context)
            text("config.json") { config?.toString(2) ?: "(aucune)" }
            text("app.json") { app(context).toString(2) }
            text("calendriers.json") { Calendars.list(context).toString(2) }
            text("agenda-aujourdhui-tous-les-calendriers.json") { allToday(context).toString(2) }
            text("rendez-vous-30-jours-tous-les-calendriers.json") { Calendars.upcoming(context, 30).toString(2) }
            text("agenda-envoye-au-moteur.json") { Calendars.forView(context, config).ifEmpty { "(rien : aucun agenda coché ni anniversaire des contacts)" } }
            text("anniversaires-contacts.json") { Calendars.birthdays(context).toString(2) }
            text("journal.txt") { Store.journal(context) }
            text("logcat.txt") { logcat() }
            // What the engine makes of it all: today's lists, the screens, an image of each.
            var engine = JSONObject()
            text("moteur.json") {
                val agenda = Calendars.forView(context, config)
                val size = Store.device(context)?.size ?: 64
                engine = JSONObject(Python.getInstance().getModule("pixelmeteo")
                    .callAttr("diagnose", config?.toString() ?: "{}", size, agenda).toString())
                val images = engine.optJSONObject("images")
                engine.remove("images")
                images?.keys()?.forEach { key ->
                    put("ecrans/$key.png", Base64.decode(images.getString(key), Base64.DEFAULT))
                }
                engine.toString(2)
            }
        }
        return save(context, name, bytes.toByteArray()) to name
    }

    private fun app(context: Context): JSONObject {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val power = context.getSystemService(PowerManager::class.java)
        val permissions = JSONObject()
        val wanted = mutableListOf(Manifest.permission.READ_CALENDAR, Manifest.permission.READ_CONTACTS)
        if (Build.VERSION.SDK_INT >= 31) wanted += listOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        for (p in wanted) permissions.put(p.substringAfterLast('.'), context.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED)
        val device = Store.device(context)
        return JSONObject()
            .put("version", info.versionName)
            .put("android", "${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
            .put("telephone", "${Build.MANUFACTURER} ${Build.MODEL}")
            .put("heure_telephone", Date().toString())
            .put("fuseau", java.util.TimeZone.getDefault().id)
            .put("cadre", device?.let { JSONObject().put("nom", it.name).put("adresse", it.address).put("taille", it.size) })
            .put("en_marche", Store.running(context))
            .put("arrete_par_moi", Store.stopped(context))
            .put("ecran_suivi", Store.followed(context))
            .put("etat", Store.status(context))
            .put("meteo_toutes_les_s", Store.refreshSeconds(context))
            .put("batterie_sans_restriction", power.isIgnoringBatteryOptimizations(context.packageName))
            .put("permissions", permissions)
    }

    /** Today's events of every calendar on the phone (ticked or not), as Android gives them. */
    private fun allToday(context: Context): JSONArray {
        val out = JSONArray()
        if (!Calendars.allowed(context)) return out.put("pas d'autorisation Agenda")
        val start = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }.timeInMillis
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon()
            .appendPath(start.toString()).appendPath((start + 24L * 3600 * 1000 - 1).toString()).build()
        val projection = arrayOf(
            CalendarContract.Instances.CALENDAR_ID, CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END, CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.EVENT_TIMEZONE,
        )
        val time = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.FRANCE)
        context.contentResolver.query(uri, projection, null, null, CalendarContract.Instances.BEGIN)?.use { c ->
            while (c.moveToNext()) {
                out.put(JSONObject()
                    .put("calendrier", c.getLong(0).toString())
                    .put("titre", c.getString(1) ?: "")
                    .put("debut", time.format(Date(c.getLong(2))))
                    .put("fin", time.format(Date(c.getLong(3))))
                    .put("journee", c.getInt(4) == 1)
                    .put("fuseau", c.getString(5) ?: ""))
            }
        }
        return out
    }

    private fun logcat(): String {
        val pid = android.os.Process.myPid()
        val process = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-v", "time", "--pid=$pid"))
        return process.inputStream.bufferedReader().readText().takeLast(400_000)
    }

    /** In Downloads (no permission needed from Android 10), else in the app's own files. */
    private fun save(context: Context, name: String, data: ByteArray): Uri {
        if (Build.VERSION.SDK_INT >= 29) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, "application/zip")
            }
            val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: error("Téléchargements inaccessibles")
            context.contentResolver.openOutputStream(uri)!!.use { it.write(data) }
            return uri
        }
        val file = File(context.getExternalFilesDir(null), name)
        file.writeBytes(data)
        return Uri.fromFile(file)
    }
}
