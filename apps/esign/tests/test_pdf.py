"""The PDF itself: the stamp, the Hebrew certificate page, and a signature that notices a changed byte.

The last test is the one that matters legally — «מסר שנחתם בחתימה אלקטרונית מאובטחת … לא שונה לאחר מועד
החתימה» (חוק חתימה אלקטרונית §3(ב)) — so it edits one byte of the signed file and expects the
signature to break.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdfsign  # noqa: E402


def source_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(72, 700, "BINA Solutions - services agreement (test)")
    c.showPage()
    c.save()
    return buf.getvalue()


def test_hebrew_is_put_in_visual_order_and_ascii_is_left_alone():
    assert pdfsign.he("abc") == "abc"
    shown = pdfsign.he("שלום")
    assert shown != "שלום"
    assert set(shown) == set("שלום")


def test_the_hebrew_font_is_in_the_image_and_has_the_letters():
    from fontTools.ttLib import TTFont
    assert os.path.exists(pdfsign.HEBREW_FONT), "DejaVu Sans must be installed in the image"
    font = TTFont(pdfsign.HEBREW_FONT)
    cmap = font.getBestCmap()
    for ch in "שלום חתימה":
        assert ord(ch) in cmap, "the font has no glyph for %r" % ch


def test_the_stamp_and_the_certificate_page_are_appended(tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(source_pdf())
    stamped = pdfsign.stamp(str(src), 1, (300, 80, 520, 160), signer_name="דנה",
                            when=__import__("datetime").datetime(2026, 11, 9, 12, 0),
                            doc_sha256="a" * 64)
    cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית",
                                    ["שם המסמך: הסכם", "החותם: דנה"], footer="נחתם בלשכת בינה")
    out = pdfsign.append_pages(stamped, cert)
    import pikepdf
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert len(pdf.pages) == 2                       # the document, then the certificate
        text = b"".join(bytes(pdf.pages[1].obj.Contents.read_bytes()) if hasattr(
            pdf.pages[1].obj.Contents, "read_bytes") else b"" for _ in [0])
        assert text                                          # the certificate page draws something


def test_the_stamp_sets_hebrew_in_visual_order_from_the_right(tmp_path, monkeypatch):
    """DGO-2029: the stamp drew «נחתם אלקטרונית» and the signer's name unreordered, from the left — reversed
    on the page. Every Hebrew line is now he()'d and set from the frame's right edge; a long name is cut in
    reading order (it loses its end, never its beginning)."""
    from reportlab.pdfgen import canvas as rl_canvas
    src = tmp_path / "in.pdf"
    src.write_bytes(source_pdf())                     # the document under test, drawn before anything is watched
    drawn = []
    monkeypatch.setattr(rl_canvas.Canvas, "drawRightString",
                        lambda self, x, y, text, *a, **k: drawn.append((x, text)))
    monkeypatch.setattr(rl_canvas.Canvas, "drawString",
                        lambda self, x, y, text, *a, **k: drawn.append(("left", text)))
    long_name = "דנה לוי " + "א" * 60 + " סוף"
    pdfsign.stamp(str(src), 1, (300, 80, 520, 160), signer_name=long_name,
                  when=__import__("datetime").datetime(2026, 11, 9, 12, 0), doc_sha256="a" * 64)
    texts = [t for _, t in drawn]
    assert not [t for x, t in drawn if x == "left"], "a line was set from the left"
    assert pdfsign.he("נחתם אלקטרונית") in texts and "נחתם אלקטרונית" not in texts
    assert pdfsign.he(long_name[:48]) in texts                    # cut first, in reading order
    assert all(x == 520 - 6 for x, _ in drawn)                    # every line from the frame's right edge


def test_the_certificate_page_really_renders_text(tmp_path):
    """Rasterised, not assumed: a page of Hebrew text has ink on it."""
    import pypdfium2 as pdfium
    cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית",
                                    ["שם המסמך: הסכם עבודה", "החותם: דנה", "מועד: 2026-11-09"],
                                    footer="נחתם בלשכת בינה")
    path = tmp_path / "cert.pdf"
    path.write_bytes(cert)
    doc = pdfium.PdfDocument(str(path))
    bitmap = doc[0].render(scale=1.5)
    pixels = bitmap.to_pil().convert("L")
    dark = sum(1 for p in pixels.getdata() if p < 200)
    assert dark > 500, "the certificate page came out blank"


@pytest.fixture(scope="module")
def signed(tmp_path_factory):
    d = tmp_path_factory.mktemp("sign")
    src = d / "in.pdf"
    src.write_bytes(source_pdf())
    stamped = pdfsign.stamp(str(src), 1, (300, 80, 520, 160), signer_name="דנה",
                            when=__import__("datetime").datetime(2026, 11, 9, 12, 0),
                            doc_sha256="a" * 64)
    cert = pdfsign.certificate_page("תעודת חתימה", ["החותם: דנה"], footer="בינה סלושנס")
    body = pdfsign.append_pages(stamped, cert)
    staged = d / "staged.pdf"
    staged.write_bytes(body)
    key, crt = pdfsign.load_or_create_cert(str(d))
    assert "BEGIN PRIVATE KEY" in key and "BEGIN CERTIFICATE" in crt
    out = d / "signed.pdf"
    pdfsign.sign(str(staged), str(out), key, crt, reason="חתימה", location="office")
    return out


def test_the_signature_validates_and_covers_the_whole_file(signed):
    got = pdfsign.verify(str(signed))
    assert got["signed"] is True
    assert got["intact"] is True
    assert got["coverage"] == "ENTIRE_FILE"


def test_changing_one_byte_after_signing_is_detected(signed, tmp_path):
    """The document half of the file — not the signature — is edited, and the signature notices."""
    data = bytearray(signed.read_bytes())
    idx = len(data) // 3
    assert idx > 0
    data[idx] = (data[idx] + 1) % 256
    tampered = tmp_path / "tampered.pdf"
    tampered.write_bytes(bytes(data))
    got = pdfsign.verify(str(tampered))
    assert got["signed"] is True and got["intact"] is False


def test_the_office_certificate_is_made_once_and_kept(tmp_path):
    key1, cert1 = pdfsign.load_or_create_cert(str(tmp_path))
    key2, cert2 = pdfsign.load_or_create_cert(str(tmp_path))
    assert key1 == key2 and cert1 == cert2
    assert (tmp_path / "signing-key.pem").exists()
    assert oct(os.stat(tmp_path / "signing-key.pem").st_mode)[-3:] == "600"


def _time_stamping_authority():
    """A time-stamping authority of the test's own (pyHanko's dummy server side): a timestamped signature is
    tested with no network, which is also what an office gets until it names one (ESIGN_TSA_URL)."""
    from datetime import datetime, timedelta, timezone

    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from pyhanko.keys import load_private_key_from_pemder_data
    try:
        from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
    except ImportError:                                   # older pyHanko kept it beside the HTTP client
        from pyhanko.sign.timestamps import DummyTimeStamper

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test time-stamping authority")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
            .sign(key, hashes.SHA256()))
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return DummyTimeStamper(tsa_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
                            tsa_key=load_private_key_from_pemder_data(key_pem, passphrase=None))


def test_a_named_time_stamping_authority_puts_a_trusted_time_in_the_signature(signed, tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(source_pdf())
    key, crt = pdfsign.load_or_create_cert(str(tmp_path / "office"))
    out = tmp_path / "signed-with-time.pdf"
    pdfsign.sign(str(src), str(out), key, crt, reason="חתימה", stamper=_time_stamping_authority())
    got = pdfsign.verify(str(out))
    assert got["intact"] is True and got["coverage"] == "ENTIRE_FILE"
    assert got["timestamped"] is True
    # no authority named (the default): no time in the signature, and nothing is called outside
    assert pdfsign.timestamper("") is None
    assert pdfsign.verify(str(signed))["timestamped"] is False
    # the key is held in memory only: nothing but the two PDFs is left beside the output
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["in.pdf", "signed-with-time.pdf"]


def test_an_office_name_too_long_or_mixed_still_gives_a_key_that_signs(tmp_path):
    """A certificate's name is at most 64 bytes, and may not mix Hebrew with Latin words: a long or mixed office
    name used to leave the office with no key at all (DGO-2029, the third and fourth readers)."""
    for office in ("BINA Solutions Digital Office Management Ltd", "בינה פתרונות טכנולוגיים מתקדמים לעסקים קטנים בע״מ",
                   "בינה Solutions"):
        d = tmp_path / str(abs(hash(office)))
        key, crt = pdfsign.load_or_create_cert(str(d), office=office)
        name = pdfsign.subject(crt)
        assert name and len(name.encode("utf-8")) <= 64, (office, name)
        src = d / "in.pdf"
        src.write_bytes(source_pdf())
        pdfsign.sign(str(src), str(d / "out.pdf"), key, crt, reason="חתימה", location=office)
        assert pdfsign.verify(str(d / "out.pdf"))["intact"] is True


def test_a_key_made_in_the_old_shared_name_is_made_again_in_the_offices_own(tmp_path):
    """Every office's key used to be made as «BINA Solutions»: on an office with its own name it is made again, once,
    and the old pair is kept beside it (the fourth reader)."""
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, pdfsign.LEGACY_NAME)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30)).sign(key, hashes.SHA256()))
    (tmp_path / "signing-key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (tmp_path / "signing-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _, kept = pdfsign.load_or_create_cert(str(tmp_path))                 # no office name: kept as it is
    assert pdfsign.subject(kept) == pdfsign.LEGACY_NAME
    _, made = pdfsign.load_or_create_cert(str(tmp_path), office="משרד בדיקה")
    assert pdfsign.subject(made) == "משרד בדיקה"
    assert (tmp_path / "signing-cert.pem.legacy").exists() and (tmp_path / "signing-key.pem.legacy").exists()
    _, again = pdfsign.load_or_create_cert(str(tmp_path), office="משרד בדיקה")   # once: now it is the office's
    assert again == made
