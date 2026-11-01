package org.idotmatrix.pixelmeteo

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.io.File

/** The phone started (or the app was updated): the Studio runs again, its routines with it, without opening the app. */
class Boot : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        // Opened once (the Studio's data), or set up as Pixel Météo before: else nothing to show yet.
        val used = File(context.filesDir, "studio").exists() ||
            context.getSharedPreferences("pixelmeteo", Context.MODE_PRIVATE).contains("address")
        if (!used) return
        try {
            StudioService.start(context)
        } catch (e: Exception) {
            Log.w("PixelStudio", "Pas démarré au lancement du téléphone", e)
        }
    }
}
