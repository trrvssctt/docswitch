package com.docswitch

import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import java.io.File
import java.util.zip.ZipFile

/**
 * Fonctions Android que les librairies ne couvrent pas :
 * - lire le fichier reçu par partage et le copier dans le cache de l'app ;
 * - compter les pages (PDF via PdfRenderer, Word via docProps/app.xml) ;
 * - détecter un PDF protégé par mot de passe avant l'envoi.
 */
class DocSwitchFilesModule(private val context: ReactApplicationContext) :
  ReactContextBaseJavaModule(context) {

  override fun getName() = NAME

  override fun initialize() {
    super.initialize()
    IncomingShare.listener = { context.emitDeviceEvent(EVENT_SHARE, null) }
  }

  override fun invalidate() {
    IncomingShare.listener = null
    super.invalidate()
  }

  /** Résout avec le fichier partagé copié en local, ou null s'il n'y en a pas. */
  @ReactMethod
  fun takeIncomingShare(promise: Promise) {
    val pending = IncomingShare.take() ?: return promise.resolve(null)
    try {
      promise.resolve(copyToCache(pending))
    } catch (e: Exception) {
      promise.reject("SHARE_READ_FAILED", "Impossible de lire le fichier reçu.", e)
    }
  }

  /** { pages: number | null, passwordProtected: boolean } */
  @ReactMethod
  fun getDocumentInfo(path: String, mimeType: String, promise: Promise) {
    val file = File(path.removePrefix("file://"))
    val result = Arguments.createMap()
    result.putBoolean("passwordProtected", false)
    result.putNull("pages")
    try {
      if (mimeType == PDF_MIME) {
        try {
          ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { fd ->
            PdfRenderer(fd).use { result.putInt("pages", it.pageCount) }
          }
        } catch (e: SecurityException) {
          result.putBoolean("passwordProtected", true)
        }
      } else {
        docxPageCount(file)?.let { result.putInt("pages", it) }
      }
    } catch (e: Exception) {
      // Fichier illisible : le serveur renverra une erreur claire, on n'affiche juste pas les pages.
    }
    promise.resolve(result)
  }

  private fun copyToCache(pending: IncomingShare.Pending): WritableMap {
    val resolver = context.contentResolver
    var name: String? = null
    resolver.query(pending.uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
      if (c.moveToFirst()) name = c.getString(0)
    }
    val safeName = (name ?: pending.uri.lastPathSegment ?: "document")
      .substringAfterLast('/')
      .replace(Regex("[\\\\:*?\"<>|]"), "_")

    val dir = File(context.cacheDir, "incoming/${System.currentTimeMillis()}").apply { mkdirs() }
    val dest = File(dir, safeName)
    resolver.openInputStream(pending.uri).use { input ->
      requireNotNull(input) { "flux vide" }
      dest.outputStream().use { input.copyTo(it) }
    }

    val mime = resolver.getType(pending.uri) ?: pending.mimeType ?: guessMime(safeName)
    return Arguments.createMap().apply {
      putString("path", dest.absolutePath)
      putString("name", safeName)
      putDouble("size", dest.length().toDouble())
      putString("mimeType", mime)
      putString("sourceApp", appLabel(pending.sourcePackage))
    }
  }

  private fun docxPageCount(file: File): Int? =
    ZipFile(file).use { zip ->
      val entry = zip.getEntry("docProps/app.xml") ?: return null
      val xml = zip.getInputStream(entry).bufferedReader().use { it.readText() }
      Regex("<Pages>(\\d+)</Pages>").find(xml)?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it > 0 }
    }

  private fun guessMime(name: String): String? =
    when (name.substringAfterLast('.', "").lowercase()) {
      "pdf" -> PDF_MIME
      "docx" -> DOCX_MIME
      else -> null
    }

  /** Nom lisible des apps les plus courantes ; null si inconnue. */
  private fun appLabel(pkg: String?): String? =
    when (pkg) {
      null -> null
      "com.whatsapp", "com.whatsapp.w4b" -> "WhatsApp"
      "com.google.android.gm" -> "Gmail"
      "org.telegram.messenger" -> "Telegram"
      "com.google.android.apps.docs" -> "Google Drive"
      else ->
        try {
          val pm = context.packageManager
          pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        } catch (e: Exception) {
          null
        }
    }

  companion object {
    const val NAME = "DocSwitchFiles"
    const val EVENT_SHARE = "DocSwitchIncomingShare"
    const val PDF_MIME = "application/pdf"
    const val DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  }
}
