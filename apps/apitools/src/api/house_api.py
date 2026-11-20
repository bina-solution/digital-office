"""/docGen/house — the office's documents in the house style, without the books (DGO-2029).

  GET  /docGen/house/types[?tax_status=patur|murshe|company]   the catalogue: every type, and which this business issues
  GET  /docGen/house/sample?type=PROPOSAL&format=pdf|html|png   a whole sample document of a type
  POST /docGen/house?format=pdf|html|png[&label=טיוטה]          the posted document, drawn — nothing is numbered or kept

The POST is how a screen shows a document while it is being written (format=html: instant, the same
HTML and CSS the PDF is drawn from), and how another app of the office draws a page in the house style
(esign's signing certificate). A document with no `supplier` is the business's own, from its settings,
in its brand. Numbering, issuing and the books stay /documents'.
"""
from flask import jsonify, make_response

from src.doc_gen import house
from src.doc_gen.house import catalogue, samples


def _business(doc):
    """The business's own masthead and brand, when the caller did not bring them."""
    if doc.get('supplier') and doc.get('brand') is not None:
        return doc
    try:
        from src.doc_data import entities
        if not doc.get('supplier'):
            doc['supplier'] = entities.issuer_party()
        if doc.get('brand') is None:
            doc['brand'] = entities.brand()
    except Exception:  # no ledger database here: the document is drawn as posted
        pass
    return doc


#: a document page opened on its own runs nothing and reads only its faces and its images
CSP = "default-src 'none'; style-src 'unsafe-inline'; font-src 'self'; img-src data:"


def _out(doc, fmt, label='', font_base=None):
    # nothing drawn here is signed, numbered or kept: its page never says «מסמך ממוחשב» (only an issued
    # document of the ledger does)
    doc['digital'] = False
    if fmt == 'html':
        resp = make_response(house.render_html(doc, label=label, font_base=font_base))
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        resp.headers['Content-Security-Policy'] = CSP
        return resp
    pdf = house.render_pdf(doc, label=label)
    if fmt == 'png':
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        d = fitz.open(stream=pdf, filetype='pdf')
        data = d[0].get_pixmap(dpi=150).tobytes('png')
        d.close()
        resp = make_response(data)
        resp.headers['Content-Type'] = 'image/png'
        return resp
    resp = make_response(pdf)
    resp.headers['Content-Type'] = 'application/pdf'
    name = (doc.get('doc_id') or catalogue.kind(doc.get('doc_type'))['code']).replace('"', '')
    resp.headers['Content-Disposition'] = f'inline; filename="{name}.pdf"'
    return resp


def types(request):
    status = request.args.get('tax_status') or ''
    rows = []
    for code in catalogue.TYPES:
        k = catalogue.kind(code)
        rows.append({'code': code, 'he': k['he'], 'en': k['en'], 'family': k['family'], 'series': k['series'],
                     'summary': k.get('summary', ''), 'prices': k['prices'], 'cover': k['cover'],
                     'offered': catalogue.may_issue(code, status) if status else True})
    return jsonify({'ok': True, 'types': rows})


def template(request):
    """What a new document of a type starts with on the screen (starters.py): chapters, clauses, terms."""
    from src.doc_gen.house import starters
    code = (request.args.get('type') or '').upper()
    if code not in catalogue.TYPES:
        return jsonify({'error': 'unknown_type', 'message': code}), 400
    return jsonify({'ok': True, 'type': code, 'document': starters.starter(code)})


def sample(request):
    code = (request.args.get('type') or '').upper()
    if code not in samples.ALL:
        return jsonify({'error': 'unknown_type', 'message': code, 'types': list(samples.ALL)}), 400
    doc = samples.signed() if request.args.get('signed') in ('1', 'true') and code == 'SERVICE_AGREEMENT' \
        else samples.sample(code)
    return _out(doc, request.args.get('format', 'pdf'), font_base=request.args.get('fonts'))


def render(request):
    doc = request.get_json(force=True, silent=True)
    if not isinstance(doc, dict) or not doc.get('doc_type'):
        return jsonify({'error': 'bad_document', 'message': 'a JSON object with a doc_type'}), 400
    try:
        k = catalogue.kind(doc['doc_type'])
    except KeyError:
        return jsonify({'error': 'unknown_type', 'message': doc['doc_type']}), 400
    return _out(_business(doc), request.args.get('format', 'pdf'), drawn_label(k, request.args.get('label', '')),
                font_base=request.args.get('fonts'))


def drawn_label(k, asked):
    """The label a posted document is drawn with. A tax document or one of the books is always a draft here: a
    «חשבונית מס» marked «מקור», with any number, drawn outside the books would be a document the software must not
    be able to make (Instruction 36; DGO-2029, the second reader). Other types keep what the caller asked."""
    return 'טיוטה' if k['family'] in ('tax', 'book') else asked


def font(name):
    """The two faces a document embeds, for a browser's preview of it (nothing else is served from here)."""
    from flask import send_from_directory
    if name not in house.FONT_FILES:
        return jsonify({'error': 'not_found'}), 404
    resp = send_from_directory(house.FONTS, name, mimetype='font/ttf')
    resp.headers['Cache-Control'] = 'public, max-age=604800'
    return resp
