"""Putting a person's signature on a PDF, and the certificate page that says how it got there.

Three steps, in this order, because the last one must cover the first two:

  1. the signature block, drawn where the sender placed it (`stamp`);
  2. the certificate page, in Hebrew, appended to the document (`certificate_page`);
  3. a PAdES signature over the whole file (`sign`) — pikepdf for the bytes, pyHanko for the crypto.

Nothing here calls an outside service: the signing key is generated once on the app's volume (or an
office PKCS#12 is loaded), the fonts are in the image, and `python-bidi` puts Hebrew in visual order for
a PDF, which has no notion of direction.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pikepdf
from bidi.algorithm import get_display
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HEBREW_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
HEBREW_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def he(text: str) -> str:
    """Hebrew (or any RTL run) in the visual order a PDF line needs; LTR text comes back unchanged."""
    return get_display(text)


def _font(bold: bool = False) -> str:
    name = "DejaVuBold" if bold else "DejaVu"
    path = HEBREW_FONT_BOLD if bold else HEBREW_FONT
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, path if os.path.exists(path) else HEBREW_FONT))
    return name


def stamp(src: str, page_index: int, box: tuple[float, float, float, float], *,
          signer_name: str, when: datetime, doc_sha256: str, note: str = "") -> bytes:
    """The visible block: a frame, the signer's name, the minute, and the document's fingerprint."""
    with pikepdf.open(src) as pdf:
        if page_index < 1 or page_index > len(pdf.pages):
            page_index = 1
        page = pdf.pages[page_index - 1]
        media = [float(v) for v in page.mediabox]
        width, height = media[2] - media[0], media[3] - media[1]
        x0, y0, x1, y1 = box
        x0 = max(0.0, min(x0, width - 10)); x1 = max(x0 + 40, min(x1, width))
        y0 = max(0.0, min(y0, height - 10)); y1 = max(y0 + 30, min(y1, height))

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        c.setStrokeColor(Color(0.16, 0.22, 0.18))
        c.setLineWidth(0.8)
        c.rect(x0, y0, x1 - x0, y1 - y0)
        c.setFont(_font(True), 8.5)
        c.setFillColor(black)
        c.drawString(x0 + 6, y1 - 13, "נחתם אלקטרונית")
        c.setFont(_font(), 7.5)
        c.drawString(x0 + 6, y1 - 24, signer_name[:48])
        c.drawString(x0 + 6, y1 - 34, when.strftime("%Y-%m-%d %H:%M %Z").strip())
        c.setFont(_font(), 6)
        c.drawString(x0 + 6, y0 + 8, "SHA-256 " + doc_sha256[:16])
        if note:
            c.setFont(_font(), 6)
            c.drawString(x0 + 6, y0 + 16, note[:70])
        c.showPage()
        c.save()
        buf.seek(0)
        overlay = pikepdf.open(buf)
        page.add_overlay(overlay.pages[0])
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


def certificate_page(title: str, lines: Iterable[str], footer: str) -> bytes:
    """A4, Hebrew, right-aligned: who signed what, when, from where, and how to check it."""
    width, height = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setFont(_font(True), 15)
    c.drawRightString(width - 56, height - 70, he(title))
    c.setLineWidth(0.6)
    c.setStrokeColor(Color(0.16, 0.22, 0.18))
    c.line(56, height - 82, width - 56, height - 82)
    y = height - 110
    c.setFillColor(black)
    for line in lines:
        c.setFont(_font(), 10)
        c.drawRightString(width - 56, y, he(line)[:120])
        y -= 17
        if y < 120:
            c.showPage()
            c.setFont(_font(), 10)
            y = height - 80
    c.setFont(_font(), 8.5)
    for line in footer.split("\n"):
        c.drawRightString(width - 56, y, he(line)[:140])
        y -= 12
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


def append_pages(pdf_bytes: bytes, extra: bytes) -> bytes:
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf, pikepdf.open(io.BytesIO(extra)) as more:
        for page in more.pages:
            pdf.pages.append(page)
        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


# ── the key ────────────────────────────────────────────────────────────────────────────────────────
def load_or_create_cert(data_dir: str, p12_path: str = "", p12_pass: str = "") -> tuple[str, str]:
    """(key_pem, cert_pem) — the office's PKCS#12 when one is connected, else a self-signed pair.

    The self-signed pair proves the bytes did not change; it does not prove WHO the signer is, which is
    the audit trail's job and, for a document that needs it, a registered CA's (research §3.3).
    """
    if p12_path and os.path.exists(p12_path):
        from cryptography.hazmat.primitives import serialization
        from pyhanko.sign.signers import SimpleSigner
        signer = SimpleSigner.load_pkcs12(p12_path, passphrase=p12_pass)
        key_pem = signer.signing_key.private_bytes(
            encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode()
        cert_pem = signer.signing_cert.public_bytes(serialization.Encoding.PEM).decode()
        return key_pem, cert_pem

    key_path = os.path.join(data_dir, "signing-key.pem")
    cert_path = os.path.join(data_dir, "signing-cert.pem")
    if os.path.exists(key_path) and os.path.exists(cert_path):
        return open(key_path, encoding="utf-8").read(), open(cert_path, encoding="utf-8").read()

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "BINA Solutions office signing (self-signed)"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BINA Solutions")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    os.makedirs(data_dir, exist_ok=True)
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write(key_pem)
    os.chmod(key_path, 0o600)
    with open(cert_path, "w", encoding="utf-8") as fh:
        fh.write(cert_pem)
    return key_pem, cert_pem


def sign(pdf_path: str, out_path: str, key_pem: str, cert_pem: str, *,
         reason: str = "", location: str = "") -> None:
    """PAdES over the whole file, into a new signature field. `out_path` must not exist yet."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter

    key_tmp = out_path + ".key.pem"
    cert_tmp = out_path + ".cert.pem"
    with open(key_tmp, "w", encoding="utf-8") as fh:
        fh.write(key_pem)
    with open(cert_tmp, "w", encoding="utf-8") as fh:
        fh.write(cert_pem)
    os.chmod(key_tmp, 0o600)
    try:
        signer = signers.SimpleSigner.load(key_file=key_tmp, cert_file=cert_tmp)
        meta = signers.PdfSignatureMetadata(
            field_name="Signature1", md_algorithm="sha256",
            subfilter=SigSeedSubFilter.PADES, reason=reason, location=location)
        with open(pdf_path, "rb") as infile, open(out_path, "wb") as outfile:
            writer = IncrementalPdfFileWriter(infile)
            fields.append_signature_field(writer, SigFieldSpec(sig_field_name="Signature1",
                                                               on_page=0, box=(0, 0, 0, 0)))
            signers.sign_pdf(writer, meta, signer=signer, output=outfile)
    finally:
        for tmp in (key_tmp, cert_tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def verify(path: str) -> dict:
    """What a second pair of eyes (or a court) asks: is the signature intact, and whose is it?"""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    with open(path, "rb") as fh:
        reader = PdfFileReader(fh)
        sigs = reader.embedded_signatures
        if not sigs:
            return {"signed": False, "intact": False, "detail": "no embedded signature"}
        try:
            status = validate_pdf_signature(sigs[0])
        except Exception as exc:
            # a file edited after signing may not even parse as a signed document any more; that IS the
            # answer to "was it changed", so it is reported, never raised at the caller
            return {"signed": True, "intact": False, "valid": False, "trusted": False,
                    "detail": str(exc)[:200], "coverage": ""}
        return {"signed": True, "intact": bool(status.intact),
                "valid": bool(status.valid), "trusted": bool(status.trusted),
                "signer": str(getattr(status, "signer_reported_subject_name", "") or ""),
                "algorithm": str(getattr(status, "md_algorithm", "") or ""),
                "coverage": status.coverage.name if status.coverage else ""}
