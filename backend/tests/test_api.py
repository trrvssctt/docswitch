"""Tests de bout en bout : à lancer dans l'image Docker (LibreOffice requis).

    docker build -t docswitch-api backend
    docker run --rm -v "$PWD/backend:/src" -w /src -u root docswitch-api \
        sh -c "pip install -q -r requirements-dev.txt && pytest -q"
"""

from __future__ import annotations

import io
import os
import time
import zipfile

os.environ.setdefault("DOCSWITCH_API_KEY", "cle-de-test")

import pymupdf as fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

import main

KEY = {"X-API-Key": os.environ["DOCSWITCH_API_KEY"]}
PDF_MIME = "application/pdf"
DOCX_MIME = main.DOCX_MIME


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def work_root_is_left_empty():
    yield
    leftovers = list(main.WORK_ROOT.iterdir())
    assert leftovers == [], f"fichiers restés sur le serveur : {leftovers}"


# --------------------------------------------------------------------------- #
# Documents de test
# --------------------------------------------------------------------------- #

def make_docx(pages: int = 1, arabic: bool = False, table: bool = False) -> bytes:
    doc = Document()
    doc.add_heading("Rapport de stage", 0)
    for i in range(pages):
        doc.add_paragraph(f"Page {i + 1}. " + "Texte de démonstration avec accents : é è à ç. " * 40)
        if arabic:
            doc.add_paragraph("هذا نص تجريبي باللغة العربية لاختبار التحويل.")
        if table:
            t = doc.add_table(rows=3, cols=3)
            for r in range(3):
                for c in range(3):
                    t.cell(r, c).text = f"L{r}C{c}"
        if i < pages - 1:
            doc.add_page_break()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(pages: int = 1, password: str | None = None, scanned: bool = False) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        if scanned:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 400), False)
            pix.clear_with(200)
            page.insert_image(page.rect, pixmap=pix)
        else:
            page.insert_textbox(fitz.Rect(50, 50, 550, 800),
                                f"Page {i + 1}\n" + "Texte de démonstration. " * 120)
    kwargs = {}
    if password:
        kwargs = dict(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    data = doc.tobytes(**kwargs)
    doc.close()
    return data


def post(client, route: str, data: bytes, name: str, mime: str, headers=KEY):
    return client.post(route, headers=headers, files={"file": (name, data, mime)})


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": main.APP_VERSION}


def test_cle_absente(client):
    r = post(client, "/convert/pdf-to-docx", make_pdf(), "a.pdf", PDF_MIME, headers={})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHORIZED"


def test_mauvaise_cle(client):
    r = post(client, "/convert/pdf-to-docx", make_pdf(), "a.pdf", PDF_MIME, headers={"X-API-Key": "faux"})
    assert r.status_code == 401


def test_pdf_vers_docx(client):
    r = post(client, "/convert/pdf-to-docx", make_pdf(3), "Rapport_de_stage.pdf", PDF_MIME)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == DOCX_MIME
    assert "Rapport_de_stage.docx" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "word/document.xml" in z.namelist()


def test_docx_vers_pdf(client):
    r = post(client, "/convert/docx-to-pdf", make_docx(2, table=True), "Facture_octobre.docx", DOCX_MIME)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == PDF_MIME
    assert r.content.startswith(b"%PDF-")


def test_nom_avec_accents(client):
    r = post(client, "/convert/docx-to-pdf", make_docx(), "Procès-verbal été.docx", DOCX_MIME)
    assert r.status_code == 200
    assert "Proc%C3%A8s-verbal%20%C3%A9t%C3%A9.pdf" in r.headers["content-disposition"]


def test_arabe_aller_retour(client):
    r = post(client, "/convert/docx-to-pdf", make_docx(arabic=True), "arabe.docx", DOCX_MIME)
    assert r.status_code == 200
    with fitz.open(stream=r.content, filetype="pdf") as pdf:
        assert "العربية" in pdf[0].get_text()
    r2 = post(client, "/convert/pdf-to-docx", r.content, "arabe.pdf", PDF_MIME)
    assert r2.status_code == 200


def test_pdf_scanne(client):
    r = post(client, "/convert/pdf-to-docx", make_pdf(2, scanned=True), "scan.pdf", PDF_MIME)
    assert r.status_code == 200


def test_pdf_protege(client):
    r = post(client, "/convert/pdf-to-docx", make_pdf(password="secret"), "p.pdf", PDF_MIME)
    assert r.status_code == 422
    assert r.json()["code"] == "PDF_PASSWORD_PROTECTED"


def test_pas_un_pdf(client):
    r = post(client, "/convert/pdf-to-docx", b"bonjour", "faux.pdf", PDF_MIME)
    assert r.status_code == 415
    assert r.json()["code"] == "INVALID_FILE"


def test_pdf_corrompu(client):
    r = post(client, "/convert/pdf-to-docx", b"%PDF-1.7\n garbage", "c.pdf", PDF_MIME)
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_FILE"


def test_pas_un_docx(client):
    r = post(client, "/convert/docx-to-pdf", make_pdf(), "faux.docx", DOCX_MIME)
    assert r.status_code == 415
    assert r.json()["code"] == "INVALID_FILE"


def test_fichier_vide(client):
    r = post(client, "/convert/docx-to-pdf", b"", "vide.docx", DOCX_MIME)
    assert r.status_code == 422


def test_sans_fichier(client):
    r = client.post("/convert/docx-to-pdf", headers=KEY)
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_FILE"


def test_trop_gros(client):
    data = b"%PDF-" + b"0" * (main.MAX_UPLOAD_BYTES + 10)
    r = post(client, "/convert/pdf-to-docx", data, "gros.pdf", PDF_MIME)
    assert r.status_code == 413
    assert r.json()["code"] == "FILE_TOO_LARGE"


def test_pdf_10_pages_en_moins_de_15_s(client):
    data = make_pdf(10)
    start = time.monotonic()
    r = post(client, "/convert/pdf-to-docx", data, "dix.pdf", PDF_MIME)
    assert r.status_code == 200
    assert time.monotonic() - start < 15
