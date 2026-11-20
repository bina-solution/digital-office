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
        # A PDF line has no direction: Hebrew goes in visual order (he()) and is set from the RIGHT edge of
        # the frame, as it reads. The text is cut in LOGICAL order first, so a long name loses its end, not
        # its beginning (DGO-2029: these lines were drawn unreordered — reversed — and left-aligned).
        right = x1 - 6
        c.setFont(_font(True), 8.5)
        c.setFillColor(black)
        c.drawRightString(right, y1 - 13, he("נחתם אלקטרונית"))
        c.setFont(_font(), 7.5)
        c.drawRightString(right, y1 - 24, he(signer_name[:48]))
        c.drawRightString(right, y1 - 34, when.strftime("%d/%m/%Y %H:%M %Z").strip())
        c.setFont(_font(), 6)
        c.drawRightString(right, y0 + 8, "SHA-256 " + doc_sha256[:16])
        if note:
            c.setFont(_font(), 6)
            c.drawRightString(right, y0 + 16, he(note[:70]))
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
        c.drawRightString(width - 56, y, he(line[:120]))      # cut in reading order, then reorder
        y -= 17
        if y < 120:
            c.showPage()
            c.setFont(_font(), 10)
            y = height - 80
    c.setFont(_font(), 8.5)
    for line in footer.split("\n"):
        c.drawRightString(width - 56, y, he(line[:140]))
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
#: the name every office's key was made with before it was made in the office's own name (DGO-2029)
LEGACY_NAME = "BINA Solutions office signing (self-signed)"


def _cert_name(value: str) -> str:
    """`value` when a certificate may carry it as a name, else ''. A name is at most 64 bytes (the cryptography
    library refuses more, and then no key is ever made — the fourth reader). asn1crypto refuses a name that mixes a
    right-to-left script with Latin letters, or that does not begin and end with a letter of that script (RFC 3454
    §6), and then pyHanko cannot sign at all (DGO-2029: «משרד בדיקה — office signing» was a 500). A name too long is
    cut on a word, then the library's own check decides."""
    value = (value or "").strip()
    while len(value.encode("utf-8")) > 64:
        cut = value.rsplit(" ", 1)[0].strip() if " " in value else value[:-1]
        value = cut
    if not value:
        return ""
    from asn1crypto import x509 as asn1_x509
    try:
        asn1_x509.Name.build({"common_name": value}).hashable
        return value
    except ValueError:
        return ""


def subject(cert_pem: str) -> str:
    """Whose key it is, as the certificate says: its common name (the signature's name in every PDF reader)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return str(names[0].value) if names else cert.subject.rfc4514_string()
    except ValueError:
        return ""


def load_or_create_cert(data_dir: str, p12_path: str = "", p12_pass: str = "",
                        office: str = "") -> tuple[str, str]:
    """(key_pem, cert_pem) — the office's PKCS#12 when one is connected, else a self-signed pair, made once, in
    the office's own name (`office`, the deployment's BUSINESS_NAME; it said «BINA Solutions» on every office).

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

    # one signing at a time looks at the office's key and makes it: two first signings at once would each make one,
    # or move a fresh key over the old pair (the fifth reader)
    import fcntl
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, ".signing-key.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _office_key(data_dir, office)


def _office_key(data_dir: str, office: str) -> tuple[str, str]:
    key_path = os.path.join(data_dir, "signing-key.pem")
    cert_path = os.path.join(data_dir, "signing-cert.pem")
    if os.path.exists(key_path) and os.path.exists(cert_path):
        key_pem, cert_pem = open(key_path, encoding="utf-8").read(), open(cert_path, encoding="utf-8").read()
        if not (office and subject(cert_pem) == LEGACY_NAME):
            return key_pem, cert_pem
        # a key made in «BINA Solutions»' name on an office that has its own: made again, once, in the office's
        # name (the fourth reader); the old pair is kept beside it, and what it signed still verifies (its
        # certificate travels inside each signed file)
        os.replace(key_path, key_path + ".legacy")
        os.replace(cert_path, cert_path + ".legacy")

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    org = _cert_name(office) or "Digital Office"
    # a Hebrew name stands alone (it may not share the name with Latin words), and so does a long one; a short Latin
    # one is said to be self-signed
    full = "%s — office signing (self-signed)" % org
    common = full if _cert_name(full) == full else org
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)])
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


def timestamper(tsa_url: str = ""):
    """An RFC 3161 time-stamping authority, when the office names one (`ESIGN_TSA_URL`): the signature then carries a
    trusted time (PAdES B-T) — what an audit trail written by the office itself cannot prove. Only the signature's
    hash travels to the authority. No URL, no timestamp: nothing here calls an outside service by default."""
    if not tsa_url:
        return None
    from pyhanko.sign.timestamps import HTTPTimeStamper
    return HTTPTimeStamper(tsa_url, timeout=20)


def sign(pdf_path: str, out_path: str, key_pem: str, cert_pem: str, *,
         reason: str = "", location: str = "", stamper=None) -> None:
    """PAdES over the whole file, into a new signature field. `out_path` must not exist yet. `stamper` (see
    timestamper()) adds a trusted time. The key is loaded in memory — it is never written to a file (DGO-2029: it
    was, beside the signed copy, for the length of a signing)."""
    from asn1crypto import pem, x509
    from pyhanko.keys import load_private_key_from_pemder_data
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    key = load_private_key_from_pemder_data(key_pem.encode("utf-8"), passphrase=None)
    raw = cert_pem.encode("utf-8")
    cert = x509.Certificate.load(pem.unarmor(raw)[2] if pem.detect(raw) else raw)
    signer = signers.SimpleSigner(signing_cert=cert, signing_key=key,
                                  cert_registry=SimpleCertificateStore.from_certs([cert]))
    meta = signers.PdfSignatureMetadata(
        field_name="Signature1", md_algorithm="sha256",
        subfilter=SigSeedSubFilter.PADES, reason=reason, location=location)
    with open(pdf_path, "rb") as infile, open(out_path, "wb") as outfile:
        writer = IncrementalPdfFileWriter(infile)
        fields.append_signature_field(writer, SigFieldSpec(sig_field_name="Signature1",
                                                           on_page=0, box=(0, 0, 0, 0)))
        signers.sign_pdf(writer, meta, signer=signer, timestamper=stamper, output=outfile)


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
                "coverage": status.coverage.name if status.coverage else "",
                # an RFC 3161 time inside the signature (ESIGN_TSA_URL), not the office's own clock
                "timestamped": getattr(status, "timestamp_validity", None) is not None}
