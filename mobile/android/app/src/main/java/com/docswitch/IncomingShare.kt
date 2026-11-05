package com.docswitch

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build

/**
 * Garde le fichier reçu par « Partager vers » / « Ouvrir avec » jusqu'à ce que le JS le lise.
 * Alimenté par MainActivity, lu par DocSwitchFilesModule.
 */
object IncomingShare {
  data class Pending(val uri: Uri, val mimeType: String?, val sourcePackage: String?)

  @Volatile var pending: Pending? = null
    private set

  /** Appelé quand un nouveau partage arrive alors que l'app tourne déjà. */
  @Volatile var listener: (() -> Unit)? = null

  fun handle(activity: Activity, intent: Intent?) {
    val uri = extractUri(intent) ?: return
    pending = Pending(uri, intent?.type, referrerPackage(activity))
    listener?.invoke()
  }

  fun take(): Pending? = pending.also { pending = null }

  private fun extractUri(intent: Intent?): Uri? =
    when (intent?.action) {
      Intent.ACTION_SEND ->
        if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)
      Intent.ACTION_VIEW -> intent.data
      else -> null
    }

  /** Paquet de l'app d'origine, quand Android le fournit (pas toujours). */
  private fun referrerPackage(activity: Activity): String? {
    val referrer = activity.referrer ?: return null
    if (referrer.scheme != "android-app") return null
    return referrer.host?.takeIf { it != activity.packageName }
  }
}
