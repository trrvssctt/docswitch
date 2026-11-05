"""DocSwitch — API de conversion PDF <-> Word."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

import converters

APP_VERSION = "1.0.0"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
CONVERSION_TIMEOUT_S = 120
CHUNK = 1024 * 1024

WORK_ROOT = Path(os.environ.get("WORK_ROOT", tempfile.gettempdir())) / "docswitch-jobs"
API_KEY = os.environ.get("DOCSWITCH_API_KEY", "")

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

log = logging.getLogger("docswitch")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# LibreOffice n'aime pas les instances parallèles sur le même profil.
libreoffice_lock = asyncio.Lock()


# --------------------------------------------------------------------------- #
# Erreurs au format {"code": ..., "message": ...}
# --------------------------------------------------------------------------- #

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def too_large() -> ApiError:
    return ApiError(413, "FILE_TOO_LARGE", "Le fichier dépasse la taille maximale de 50 Mo.")


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #

def purge_work_root() -> None:
    """Supprime d'éventuels restes (crash, redémarrage brutal)."""
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT, ignore_errors=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.chmod(0o700)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not API_KEY:
        raise RuntimeError("DOCSWITCH_API_KEY n'est pas défini")
    purge_work_root()
    yield
    purge_work_root()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return error_response(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError):
    return error_response(422, "INVALID_FILE", "Aucun fichier valide n'a été reçu.")


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception):
    log.error("erreur inattendue: %s", type(exc).__name__)
    return error_response(500, "CONVERSION_FAILED", "Une erreur est survenue sur le serveur.")


def api_key_is_valid(key: str | None) -> bool:
    return bool(key) and secrets.compare_digest(key.encode(), API_KEY.encode())


async def drain_body(receive) -> None:
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body", False):
            return


class GuardAndLog:
    """Middleware ASGI pur (et non @app.middleware("http"), qui empêche
    request.is_disconnected() de voir le départ du client).

    Vérifie la clé et la taille annoncée AVANT la lecture du corps : un envoi
    refusé n'est jamais stocké.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.monotonic()
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        declared = headers.get("content-length", "")
        status = 0

        async def send_and_record(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        if scope["path"].startswith("/convert/") and not api_key_is_valid(headers.get("x-api-key")):
            response = error_response(401, "UNAUTHORIZED", "Clé d'API absente ou invalide.")
        elif declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES + CHUNK:
            response = error_response(413, "FILE_TOO_LARGE", "Le fichier dépasse la taille maximale de 50 Mo.")
        else:
            response = self.app
        if response is not self.app:
            # Lire et jeter le corps (sans le stocker) : sinon Nginx voit une connexion
            # coupée en plein envoi et renvoie un 502 au lieu de notre erreur.
            await drain_body(receive)
        try:
            await response(scope, receive, send_and_record)
        finally:
            # Uniquement méthode, route, statut et durée : jamais de nom ni de contenu de fichier.
            log.info("%s %s -> %s (%.1fs)", scope["method"], scope["path"], status or "-",
                     time.monotonic() - start)


app.add_middleware(GuardAndLog)


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #

async def save_upload(upload: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise too_large()
            out.write(chunk)
    if size == 0:
        raise ApiError(422, "INVALID_FILE", "Le fichier est vide.")


def output_name(original: str | None, ext: str) -> str:
    stem = Path(original or "document").stem.strip() or "document"
    return stem + ext


def stream_and_forget(path: Path, filename: str, media_type: str) -> StreamingResponse:
    """Ouvre le résultat puis supprime le dossier de travail immédiatement.

    Sous Linux le descripteur ouvert reste lisible : le fichier n'existe plus sur
    le disque, même si le client se déconnecte en plein téléchargement.
    """
    f = path.open("rb")
    length = os.fstat(f.fileno()).st_size

    def iterate():
        try:
            while chunk := f.read(CHUNK):
                yield chunk
        finally:
            f.close()

    headers = {
        "Content-Length": str(length),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(iterate(), media_type=media_type, headers=headers)


async def convert(request: Request, file: UploadFile, kind: str) -> StreamingResponse:
    job_dir = WORK_ROOT / uuid.uuid4().hex
    job_dir.mkdir(mode=0o700)
    try:
        if kind == "pdf2docx":
            src, dst = job_dir / "input.pdf", job_dir / "output.docx"
        else:
            src, dst = job_dir / "input.docx", job_dir / "output.pdf"

        await save_upload(file, src)
        await file.close()

        if kind == "pdf2docx":
            if not converters.looks_like_pdf(src):
                raise ApiError(415, "INVALID_FILE", "Ce fichier n'est pas un PDF.")
            state = await asyncio.to_thread(converters.inspect_pdf, src)
            if state == "protected":
                raise ApiError(422, "PDF_PASSWORD_PROTECTED", "Ce PDF est protégé par un mot de passe.")
            if state == "invalid":
                raise ApiError(422, "INVALID_FILE", "Ce PDF est corrompu ou illisible.")
        elif not converters.looks_like_docx(src):
            raise ApiError(415, "INVALID_FILE", "Ce fichier n'est pas un document Word (.docx).")

        try:
            if kind == "pdf2docx":
                await converters.pdf_to_docx(src, dst, CONVERSION_TIMEOUT_S, request.is_disconnected)
            else:
                async with libreoffice_lock:
                    await converters.docx_to_pdf(src, dst, CONVERSION_TIMEOUT_S, request.is_disconnected)
        except converters.ConversionCancelled:
            log.info("conversion annulée par le client")
            # Le client est parti : personne ne lira cette réponse.
            return error_response(499, "CANCELLED", "Conversion annulée.")
        except converters.ConversionTimeout:
            raise ApiError(500, "CONVERSION_FAILED", "La conversion a pris trop de temps.")
        except converters.ConversionError:
            log.warning("échec de conversion %s", kind)
            raise ApiError(500, "CONVERSION_FAILED", "La conversion a échoué.")

        if kind == "pdf2docx":
            return stream_and_forget(dst, output_name(file.filename, ".docx"), DOCX_MIME)
        return stream_and_forget(dst, output_name(file.filename, ".pdf"), PDF_MIME)
    finally:
        # Sur succès le résultat est déjà ouvert : on peut tout supprimer.
        shutil.rmtree(job_dir, ignore_errors=True)


@app.post("/convert/pdf-to-docx")
async def pdf_to_docx(request: Request, file: UploadFile):
    return await convert(request, file, "pdf2docx")


@app.post("/convert/docx-to-pdf")
async def docx_to_pdf(request: Request, file: UploadFile):
    return await convert(request, file, "docx2pdf")
