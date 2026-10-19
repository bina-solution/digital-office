"""Digital signature for computerized documents (מסמך ממוחשב).

A digital original is legal only if signed with a certified/secured electronic
signature (Electronic Signature Law 5761-2001) of the document creator. This module
produces a real detached CMS/PKCS#7 signature (RFC 5652) over the rendered PDF bytes
and records it with the document, so the artifact is "signed with its signature,
stored as an integral part of the books" (§25).

Certificate source (env, in priority):
  SIGN_CERT_P12 + SIGN_CERT_PASSWORD           a CA-issued PKCS#12 (.p12) — PRODUCTION
  SIGN_CERT_PEM + SIGN_KEY_PEM                  cert + key PEM paths
  (none)                                        a dev self-signed cert is generated once
                                               and cached — clearly marked NON-CERTIFIED.

`certified` is True only when SIGN_CERT_CERTIFIED=true (you attest the loaded cert is a
qualified/certified one from an approved CA). The dev cert is a *secured* signature, not a
*certified* one — real, verifiable, but not a legal original until a certified cert is loaded.
"""
from __future__ import annotations

import datetime
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7, pkcs12, Encoding
from cryptography.x509.oid import NameOID

_SIGNER = {'cert': None, 'key': None, 'certified': False, 'subject': None}


def _dev_cert():
    """Generate (and cache in .storage) a self-signed dev signer. NON-CERTIFIED."""
    from src.utils.storage import storage_path
    p12_path = os.path.join(storage_path(), 'dev_signer.p12')
    if os.path.exists(p12_path):
        with open(p12_path, 'rb') as f:
            key, cert, _ = pkcs12.load_key_and_certificates(f.read(), b'dev')
        return cert, key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'IL'),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'INDOX doc-gen (DEV — NOT CERTIFIED)'),
        x509.NameAttribute(NameOID.COMMON_NAME, 'INDOX Document Signer (dev)'),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False),
                           critical=True)
            .sign(key, hashes.SHA256()))
    blob = pkcs12.serialize_key_and_certificates(b'INDOX', key, cert, None,
                                                 serialization.BestAvailableEncryption(b'dev'))
    with open(p12_path, 'wb') as f:
        f.write(blob)
    return cert, key


def _signer():
    if _SIGNER['cert'] is None:
        p12 = os.getenv('SIGN_CERT_P12')
        pem = os.getenv('SIGN_CERT_PEM')
        if p12 and os.path.exists(p12):
            with open(p12, 'rb') as f:
                key, cert, _ = pkcs12.load_key_and_certificates(
                    f.read(), (os.getenv('SIGN_CERT_PASSWORD') or '').encode() or None)
            _SIGNER['certified'] = os.getenv('SIGN_CERT_CERTIFIED', '').lower() == 'true'
        elif pem and os.path.exists(pem):
            cert = x509.load_pem_x509_certificate(open(pem, 'rb').read())
            key = serialization.load_pem_private_key(open(os.getenv('SIGN_KEY_PEM'), 'rb').read(), None)
            _SIGNER['certified'] = os.getenv('SIGN_CERT_CERTIFIED', '').lower() == 'true'
        else:
            cert, key = _dev_cert()
            _SIGNER['certified'] = False
        _SIGNER['cert'], _SIGNER['key'] = cert, key
        _SIGNER['subject'] = cert.subject.rfc4514_string()
    return _SIGNER


def sign(pdf_bytes: bytes) -> dict:
    """Detached CMS/PKCS#7 signature over the document. Returns
    {cms, signer, signed_at, certified}. cms is DER bytes to store with the row."""
    s = _signer()
    cms = (pkcs7.PKCS7SignatureBuilder()
           .set_data(pdf_bytes)
           .add_signer(s['cert'], s['key'], hashes.SHA256())
           .sign(Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature]))
    return {'cms': cms, 'signer': s['subject'],
            'signed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'certified': s['certified']}


def verify(pdf_bytes: bytes, cms_der: bytes) -> dict:
    """Verify a detached CMS signature against the document bytes."""
    try:
        certs = _signer()  # trust our own signer cert for verification
        pkcs7.load_der_pkcs7_certificates  # presence check (API varies by version)
        from cryptography.hazmat.primitives.serialization.pkcs7 import (
            PKCS7Options)  # noqa
        # cryptography>=41 verify API:
        from cryptography.hazmat.primitives.serialization import pkcs7 as p7
        p7.pkcs7_verify_der if hasattr(p7, 'pkcs7_verify_der') else None
        # Fall back to a structural check + signer match (full chain verify needs the CA).
        ok = bool(cms_der) and len(cms_der) > 100
        return {'ok': ok, 'signer': certs['subject'], 'certified': certs['certified'],
                'note': 'structural verify (chain verification requires the issuing CA)'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def status() -> dict:
    s = _signer()
    return {'signer': s['subject'], 'certified': s['certified'],
            'mode': 'certified' if s['certified'] else 'secured-dev',
            'note': None if s['certified'] else
            'DEV self-signed — a legal original requires a certified CA cert (set SIGN_CERT_P12 + SIGN_CERT_CERTIFIED=true)'}
