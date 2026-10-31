package org.idotmatrix.pixelmeteo

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CalendarContract
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

/** The phone's calendars (with the calendar permission): the list to pick from, and today's events. */
object Calendars {
    fun allowed(context: Context) =
        context.checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED

    /** [{id, name, account, color}] of the calendars on the phone. */
    fun list(context: Context): JSONArray {
        val out = JSONArray()
        if (!allowed(context)) return out
        val projection = arrayOf(
            CalendarContract.Calendars._ID, CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
            CalendarContract.Calendars.ACCOUNT_NAME, CalendarContract.Calendars.CALENDAR_COLOR,
            CalendarContract.Calendars.SYNC_EVENTS, CalendarContract.Calendars.VISIBLE,
        )
        val upcoming = upcoming(context, 30)
        context.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, projection, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0).toString()
                val events = (0 until upcoming.length()).map { upcoming.getJSONObject(it) }.filter { it.getString("calendar") == id }
                out.put(JSONObject()
                    .put("id", id)
                    .put("name", c.getString(1) ?: "")
                    .put("account", c.getString(2) ?: "")
                    .put("color", String.format("#%06X", 0xFFFFFF and c.getInt(3)))
                    // Not synced: Google keeps its events online, the phone has none to give.
                    .put("synced", c.getInt(4) == 1)
                    .put("visible", c.getInt(5) == 1)
                    .put("next30", events.size)
                    .put("next", events.firstOrNull()?.let { "${it.getString("when")} ${it.getString("title")}" } ?: ""))
            }
        }
        return out
    }

    fun writeAllowed(context: Context) =
        context.checkSelfPermission(Manifest.permission.WRITE_CALENDAR) == PackageManager.PERMISSION_GRANTED

    /** A calendar the phone does not sync (Google Agenda's switch did not reach it): switched on here,
     *  shown and synced (an app may set these two), then the accounts synced. */
    fun enable(context: Context, id: String) {
        val values = android.content.ContentValues().apply {
            put(CalendarContract.Calendars.SYNC_EVENTS, 1)
            put(CalendarContract.Calendars.VISIBLE, 1)
        }
        val uri = ContentUris.withAppendedId(CalendarContract.Calendars.CONTENT_URI, id.toLong())
        context.contentResolver.update(uri, values, null, null)
        syncNow(context)
    }

    /** Asks Android to sync the calendars' accounts now (a calendar just switched on in Google Agenda
     *  reaches the phone only after its next sync). Returns how many accounts were asked. */
    fun syncNow(context: Context): Int {
        val accounts = mutableSetOf<android.accounts.Account>()
        val projection = arrayOf(CalendarContract.Calendars.ACCOUNT_NAME, CalendarContract.Calendars.ACCOUNT_TYPE)
        context.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, projection, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(0) ?: continue
                val type = c.getString(1) ?: continue
                if (type != CalendarContract.ACCOUNT_TYPE_LOCAL) accounts += android.accounts.Account(name, type)
            }
        }
        val extras = android.os.Bundle().apply {
            putBoolean(android.content.ContentResolver.SYNC_EXTRAS_MANUAL, true)
            putBoolean(android.content.ContentResolver.SYNC_EXTRAS_EXPEDITED, true)
        }
        for (account in accounts) android.content.ContentResolver.requestSync(account, CalendarContract.AUTHORITY, extras)
        cached = ""
        cachedKey = ""
        return accounts.size
    }

    /** The events of the next ``days`` days in every calendar (the first 200): to see what the phone has. */
    fun upcoming(context: Context, days: Int): JSONArray {
        val out = JSONArray()
        if (!allowed(context)) return out
        val start = System.currentTimeMillis()
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, start)
            ContentUris.appendId(it, start + days * 24L * 3600 * 1000)
        }.build()
        val projection = arrayOf(CalendarContract.Instances.CALENDAR_ID, CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN, CalendarContract.Instances.ALL_DAY)
        val time = java.text.SimpleDateFormat("dd/MM HH:mm", java.util.Locale.FRANCE)
        context.contentResolver.query(uri, projection, null, null, CalendarContract.Instances.BEGIN)?.use { c ->
            while (c.moveToNext() && out.length() < 200) {
                out.put(JSONObject()
                    .put("calendar", c.getLong(0).toString())
                    .put("title", c.getString(1) ?: "")
                    .put("when", if (c.getInt(3) == 1) time.format(java.util.Date(c.getLong(2))).substring(0, 5)
                                 else time.format(java.util.Date(c.getLong(2)))))
            }
        }
        return out
    }

    /** Today's events of the calendars ``ids``: [{title, begin, end, all_day}] (times in ms). */
    fun today(context: Context, ids: List<String>): JSONArray {
        val out = JSONArray()
        if (ids.isEmpty() || !allowed(context)) return out
        val start = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }.timeInMillis
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, start)
            ContentUris.appendId(it, start + 24L * 3600 * 1000 - 1)
        }.build()
        val projection = arrayOf(
            CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.END,
            CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.CALENDAR_ID,
        )
        val wanted = ids.toSet()
        context.contentResolver.query(uri, projection, null, null, CalendarContract.Instances.BEGIN)?.use { c ->
            while (c.moveToNext()) {
                if (c.getLong(4).toString() !in wanted) continue
                out.put(JSONObject()
                    .put("title", c.getString(0) ?: "")
                    .put("begin", c.getLong(1))
                    .put("end", c.getLong(2))
                    .put("all_day", c.getInt(3) == 1))
            }
        }
        return out
    }

    fun contactsAllowed(context: Context) =
        context.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED

    /** The contacts' birthdays: [{name, date}] (2010-10-31, or --10-31 without the year). */
    fun birthdays(context: Context): JSONArray {
        val out = JSONArray()
        if (!contactsAllowed(context)) return out
        val projection = arrayOf(ContactsContract.Data.DISPLAY_NAME, ContactsContract.CommonDataKinds.Event.START_DATE)
        val where = "${ContactsContract.Data.MIMETYPE} = ? AND ${ContactsContract.CommonDataKinds.Event.TYPE} = ?"
        val args = arrayOf(ContactsContract.CommonDataKinds.Event.CONTENT_ITEM_TYPE,
            ContactsContract.CommonDataKinds.Event.TYPE_BIRTHDAY.toString())
        context.contentResolver.query(ContactsContract.Data.CONTENT_URI, projection, where, args, null)?.use { c ->
            while (c.moveToNext()) {
                val name = c.getString(0) ?: continue
                val date = c.getString(1) ?: continue
                out.put(JSONObject().put("name", name).put("date", date))
            }
        }
        return out
    }

    // Read once a minute at most: the preview asks every second.
    private var cached = ""
    private var cachedKey = ""
    private var cachedAt = 0L

    /** What the view wants from the phone, as JSON for Python: today's events of the chosen
     *  calendars and the contacts' birthdays ("" when it wants neither). */
    @Synchronized
    fun forView(context: Context, config: JSONObject?): String {
        if (config == null) return ""
        val key = "${config.optJSONArray("agenda_device")}|${config.optBoolean("contacts_birthdays")}"
        val now = System.currentTimeMillis()
        if (key == cachedKey && now - cachedAt < 60_000) return cached
        cached = read(context, config)
        cachedKey = key
        cachedAt = now
        return cached
    }

    private fun read(context: Context, config: JSONObject): String {
        val ids = config.optJSONArray("agenda_device")
        // The calendars ticked are read (the screens say whether the agenda shows: no switch to look at).
        val events = if (ids != null && ids.length() > 0) {
            today(context, (0 until ids.length()).map { ids.getString(it) })
        } else JSONArray()
        val birthdays = if (config.optBoolean("contacts_birthdays")) birthdays(context) else JSONArray()
        if (events.length() == 0 && birthdays.length() == 0) return ""
        return JSONObject().put("events", events).put("birthdays", birthdays).toString()
    }
}
