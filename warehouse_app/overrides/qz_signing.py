"""QZ Tray signing for submitted Purchase Receipt labels."""

import base64
import re
from pathlib import Path

import frappe
from frappe import _
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from warehouse_app.overrides.purchase_receipt import _receipt


def _files():
    base = Path(frappe.get_site_path("private", "qz_signing"))
    return base / "digital-certificate.txt", base / "private-key.pem"


@frappe.whitelist()
def certificate(purchase_receipt):
    _receipt(purchase_receipt)
    cert_path, _key_path = _files()
    try:
        return cert_path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        frappe.throw(_("Sertifikat QZ Tray belum tersedia di server."))


@frappe.whitelist(methods=["POST"])
def sign(purchase_receipt, request):
    _receipt(purchase_receipt)
    if not isinstance(request, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", request):
        frappe.throw(_("Permintaan tanda tangan QZ Tray tidak valid."))
    _cert_path, key_path = _files()
    try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        frappe.throw(_("Private key QZ Tray belum tersedia atau tidak valid di server."))
    if not isinstance(private_key, rsa.RSAPrivateKey):
        frappe.throw(_("Private key QZ Tray harus menggunakan RSA."))
    signature = private_key.sign(request.encode("utf-8"), padding.PKCS1v15(), hashes.SHA512())
    return base64.b64encode(signature).decode("ascii")
