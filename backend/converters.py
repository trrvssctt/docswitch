"""Conversions PDF <-> Word.

Chaque conversion tourne dans un sous-processus pour pouvoir être tuée
(timeout de 120 s ou client déconnecté) sans bloquer le serveur.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import zipfile
from pathlib import Path

LIBREOFFICE_PROFILE = Path(os.environ.get("LIBREOFFICE_PROFILE", "/tmp/docswitch-lo-profile"))


class ConversionError(Exception):
    """La conversion a échoué (fichier illisible côté convertisseur, crash...)."""


class ConversionTimeout(ConversionError):
    pass


class ConversionCancelled(ConversionError):
    pass


# --------------------------------------------------------------------------- #
# Validation des fichiers reçus
# --------------------------------------------------------------------------- #

def looks_like_pdf(path: Path) -> bool:
    with path.open("rb") as f:
        # La spec tolère quelques octets avant l'en-tête.
        return b"%PDF-" in f.read(1024)


def looks_like_docx(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def inspect_pdf(path: Path) -> str:
    """Retourne "ok", "protected" ou "invalid"."""
    import pymupdf as fitz  # installé avec pdf2docx

    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                return "protected"
            if doc.page_count == 0:
                return "invalid"
    except Exception:
        return "invalid"
    return "ok"


# --------------------------------------------------------------------------- #
# Exécution des sous-processus
# --------------------------------------------------------------------------- #

async def _run(cmd: list[str], timeout: float, is_cancelled, env: dict | None = None) -> None:
    """Lance `cmd`, le tue si timeout ou si `is_cancelled()` devient vrai."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # groupe de processus à part : soffice lance soffice.bin
        env=env,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    wait_task = asyncio.ensure_future(proc.communicate())
    try:
        while True:
            done, _ = await asyncio.wait({wait_task}, timeout=0.5)
            if done:
                break
            if loop.time() > deadline:
                raise ConversionTimeout()
            if await is_cancelled():
                raise ConversionCancelled()
    except BaseException:
        _kill_group(proc)
        wait_task.cancel()
        raise

    _, stderr = wait_task.result()
    if proc.returncode != 0:
        # stderr peut contenir du texte du document : on ne garde que la fin, pour debug local.
        raise ConversionError(f"code {proc.returncode}: {stderr[-300:].decode(errors='replace')}")


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# --------------------------------------------------------------------------- #
# Conversions
# --------------------------------------------------------------------------- #

async def pdf_to_docx(src: Path, dst: Path, timeout: float, is_cancelled) -> None:
    cmd = [sys.executable, "-m", "converters", "pdf2docx", str(src), str(dst)]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    await _run(cmd, timeout, is_cancelled, env=env)
    if not dst.exists() or dst.stat().st_size == 0:
        raise ConversionError("aucun fichier produit")


async def docx_to_pdf(src: Path, dst: Path, timeout: float, is_cancelled) -> None:
    """LibreOffice headless. L'appelant doit tenir le verrou LibreOffice."""
    out_dir = dst.parent
    cmd = [
        "soffice",
        f"-env:UserInstallation=file://{LIBREOFFICE_PROFILE}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        str(out_dir),
        str(src),
    ]
    await _run(cmd, timeout, is_cancelled)
    produced = out_dir / (src.stem + ".pdf")
    if not produced.exists() or produced.stat().st_size == 0:
        raise ConversionError("aucun fichier produit")
    if produced != dst:
        produced.rename(dst)


def _pdf2docx_worker(src: str, dst: str) -> None:
    import logging

    from pdf2docx import Converter

    # pdf2docx est bavard ; on évite que des fragments du document finissent dans les logs.
    logging.disable(logging.CRITICAL)
    cv = Converter(src)
    try:
        cv.convert(dst)
    finally:
        cv.close()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "pdf2docx":
        _pdf2docx_worker(sys.argv[2], sys.argv[3])
    else:
        sys.exit("usage: python -m converters pdf2docx SRC DST")
