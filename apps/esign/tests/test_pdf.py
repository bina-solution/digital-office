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
    stamped = pdfsign.stamp(str(src), 1, (300, 80, 520, 160), signer_name="ברוך",
                            when=__import__("datetime").datetime(2026, 11, 9, 12, 0),
                            doc_sha256="a" * 64)
    cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית",
                                    ["שם המסמך: הסכם", "החותם: ברוך"], footer="נחתם בלשכת בינה")
    out = pdfsign.append_pages(stamped, cert)
    import pikepdf
    with pikepdf.open(io.BytesIO(out)) as pdf:
        assert len(pdf.pages) == 2                       # the document, then the certificate
        text = b"".join(bytes(pdf.pages[1].obj.Contents.read_bytes()) if hasattr(
            pdf.pages[1].obj.Contents, "read_bytes") else b"" for _ in [0])
        assert text                                          # the certificate page draws something


def test_the_certificate_page_really_renders_text(tmp_path):
    """Rasterised, not assumed: a page of Hebrew text has ink on it."""
    import pypdfium2 as pdfium
    cert = pdfsign.certificate_page("תעודת חתימה אלקטרונית",
                                    ["שם המסמך: הסכם עבודה", "החותם: ברוך", "מועד: 2026-11-09"],
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
    stamped = pdfsign.stamp(str(src), 1, (300, 80, 520, 160), signer_name="ברוך",
                            when=__import__("datetime").datetime(2026, 11, 9, 12, 0),
                            doc_sha256="a" * 64)
    cert = pdfsign.certificate_page("תעודת חתימה", ["החותם: ברוך"], footer="בינה סלושנס")
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
