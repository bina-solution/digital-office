"""gallery — render every sample document: the PDF, its pages as PNG, and the HTML (DGO-2029).

    python3 -m src.doc_gen.house.gallery <outdir> [TYPE …]
    GALLERY_FONTS=api/docGen/house/fonts/ python3 -m src.doc_gen.house.gallery <outdir>   # + <TYPE>.web.html

Writes <TYPE>.pdf, <TYPE>.html and <TYPE>-pNN.png for each type, plus the signed agreement and a draft,
and prints one line per document: pages, seconds, bytes. It is how the house style is looked at, page
by page, before anything is landed. With GALLERY_FONTS, each document's HTML is also written for a browser
(<TYPE>.web.html): the faces asked of that relative path, the sheet drawn by house.css's @media screen.
"""
import os
import sys
import time

from . import catalogue, render_html, render_pdf, samples

#: the label a document carries when the gallery prints it: the books' documents are «מקור»
LABEL = {'tax': 'מקור', 'book': 'מקור'}


def _pages(pdf, out, name, dpi):
    try:
        import pymupdf as fitz
    except ImportError:  # older PyMuPDF
        import fitz
    d = fitz.open(stream=pdf, filetype='pdf')
    for i, page in enumerate(d):
        page.get_pixmap(dpi=dpi).save(os.path.join(out, f'{name}-p{i + 1:02d}.png'))
    n = len(d)
    d.close()
    return n


def build(out, types=None, dpi=110):
    os.makedirs(out, exist_ok=True)
    jobs = [(t, samples.sample(t), LABEL.get(catalogue.kind(t)['family'], '')) for t in (types or samples.ALL)]
    if not types:
        jobs.append(('SERVICE_AGREEMENT-signed', samples.signed(), ''))
        jobs.append(('INVOICE-draft', samples.sample('INVOICE'), 'טיוטה'))
    rows = []
    for name, doc, label in jobs:
        t0 = time.time()
        html = render_html(doc, label=label)
        with open(os.path.join(out, f'{name}.html'), 'w', encoding='utf-8') as f:
            f.write(html)
        if os.environ.get('GALLERY_FONTS'):
            with open(os.path.join(out, f'{name}.web.html'), 'w', encoding='utf-8') as f:
                f.write(render_html(doc, label=label, font_base=os.environ['GALLERY_FONTS']))
        pdf = render_pdf(doc, label=label)
        with open(os.path.join(out, f'{name}.pdf'), 'wb') as f:
            f.write(pdf)
        n = _pages(pdf, out, name, dpi)
        rows.append((name, n, time.time() - t0, len(pdf)))
        print(f'{name:28s} {n} page(s)  {time.time() - t0:5.2f}s  {len(pdf):>8,d} bytes', flush=True)
    return rows


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    build(sys.argv[1], sys.argv[2:] or None)
