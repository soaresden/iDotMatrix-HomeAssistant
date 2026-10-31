package org.idotmatrix.pixelmeteo

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** The phone started (or the app was updated): the frame gets the view again, without opening the app. */
class Boot : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (Store.device(context) == null || Store.config(context) == null || Store.stopped(context)) return
        try {
            MeteoService.start(context)
        } catch (e: Exception) {
            Store.status(context, "Pas démarré au lancement du téléphone : ouvre l'appli")
        }
    }
}
