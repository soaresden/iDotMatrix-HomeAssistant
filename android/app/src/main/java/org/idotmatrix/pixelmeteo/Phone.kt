package org.idotmatrix.pixelmeteo

import android.content.Context
import org.json.JSONArray

/** The phone for the Studio's Python (python/phone.py): its calendars and its contacts' birthdays. */
object Phone {
    lateinit var context: Context

    /** [{id, name, account, synced}] of the calendars on the phone (none without the permission). */
    @JvmStatic
    fun calendars(): String = Calendars.list(context).toString()

    /** The events of the calendars [ids] (a JSON list) from [start] to [end] (ms). */
    @JvmStatic
    fun events(ids: String, start: Long, end: Long): String {
        val list = JSONArray(ids)
        return Calendars.between(context, (0 until list.length()).map { list.getString(it) }, start, end).toString()
    }

    /** The contacts' birthdays: [{name, date}]. */
    @JvmStatic
    fun birthdays(): String = Calendars.birthdays(context).toString()
}
