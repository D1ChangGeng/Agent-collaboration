"""Pure MIME/container evidence plus actual admitted platform CAS roundtrip.

Tiny binary builders exercise container boundaries, not image/PDF decoding or
malware safety. FakeCAS is a test double, never a second production blob store.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import struct
import sys
import zipfile
import zlib
from urllib.parse import unquote

import pytest

from runtime.artifacts import LocalArtifactStore, WindowsArtifactStore
from runtime.communication_attachment_content import (
    DEFAULT_ATTACHMENT_BYTES,
    AttachmentContentError,
    AttachmentIntegrityError,
    attachment_content_disposition,
    normalize_attachment_media_type,
    put_attachment_content,
    read_attachment_content,
    validate_attachment_content,
    validate_attachment_name,
)
from runtime.models import ArtifactRef


def descriptor(data, media_type="application/octet-stream"):
    return {"declared_bytes": len(data), "declared_sha256": hashlib.sha256(data).hexdigest(), "media_type": media_type}


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\xff")) + chunk(b"IEND", b"")


def jpeg():
    frame = b"\xff\xc0" + struct.pack(">H", 11) + struct.pack(">BHHB", 8, 1, 1, 1) + b"\x01\x11\0"
    scan = b"\xff\xda\0\x08\x01\x01\0\0\x3f\0" + b"\x11\xff\0\x22"
    return b"\xff\xd8" + frame + scan + b"\xff\xd9"


def webp(*, animated=False):
    image = b"VP8L" + struct.pack("<I", 5) + b"\x2f\0\0\0\0\0"
    if animated:
        frame = b"\0" * 16 + image
        image = b"ANMF" + struct.pack("<I", len(frame)) + frame
    return b"RIFF" + struct.pack("<I", len(image) + 4) + b"WEBP" + image


def pdf():
    prefix = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    return prefix + b"xref\n0 2\n0000000000 65535 f\n0000000009 00000 n\ntrailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n" + str(len(prefix)).encode() + b"\n%%EOF\n"


def archive():
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("../untrusted-name.txt", b"untrusted bytes; never extracted")
    return result.getvalue()


VALID_CONTAINERS = [("image/png", png()), ("image/jpeg", jpeg()),
    ("image/gif", base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")),
    ("image/webp", webp()), ("image/webp", webp(animated=True)), ("application/pdf", pdf()), ("application/zip", archive())]


@pytest.mark.parametrize("media,data", VALID_CONTAINERS, ids=["png", "jpeg", "gif", "webp", "webp-frame", "pdf", "zip"])
def test_common_binary_container_evidence_does_not_decode_or_extract(media, data, monkeypatch):
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_args, **_kwargs: pytest.fail("attachment validator decompressed a member"))
    monkeypatch.setattr(zipfile.ZipFile, "extractall", lambda *_args, **_kwargs: pytest.fail("attachment validator extracted a member"))
    verified = validate_attachment_content(data, **descriptor(data, media), upload_content_type=media)
    assert verified.evidence == "bounded_container" and verified.size_bytes == len(data)
    assert verified.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("media", ["text/plain", "text/markdown", "text/csv", "text/html"])
def test_utf8_text_categories_remain_untrusted_raw_bytes(media):
    data = "汉字🧭<script>untrusted()</script>\n".encode()
    result = validate_attachment_content(data, **descriptor(data, media + "; charset=\"UTF-8\""), upload_content_type=media)
    assert result.media_type == media and result.evidence == "utf8_encoding"


@pytest.mark.parametrize("media,data,evidence", [
    ("application/json", b'{"value":[1,true,null]}', "json_structure"),
    ("application/vnd.fixture+json", b'"A JSON scalar"', "json_structure"),
    ("image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"><script>untrusted()</script><image href="https://example.invalid/private"/></svg>', "svg_xml_container"),
])
def test_structured_text_is_bounded_content_evidence_not_execution(media, data, evidence):
    assert validate_attachment_content(data, **descriptor(data, media)).evidence == evidence


@pytest.mark.parametrize("data,media", [(b"\xff", "text/plain"), (b"x\0y", "text/markdown"),
    (b'{"x":NaN}', "application/json"), (b'{bad}', "application/json"),
    (b'<html/>', "image/svg+xml"), (b'<svg><g></svg>', "image/svg+xml"),
    (b'<!DOCTYPE svg [<!ENTITY x "value">]><svg>&x;</svg>', "image/svg+xml"),
    (b'<?xml version="1.0" encoding="ISO-8859-1"?><svg/>', "image/svg+xml")])
def test_wrong_utf8_or_structured_types_are_rejected(data, media):
    with pytest.raises(AttachmentContentError):
        validate_attachment_content(data, **descriptor(data, media))


def test_structural_complexity_requires_explicit_octet_stream_fallback():
    data = b"[" * 65 + b"0" + b"]" * 65
    with pytest.raises(AttachmentContentError) as error:
        validate_attachment_content(data, **descriptor(data, "application/json"))
    assert error.value.code == "capability_unsupported"
    assert validate_attachment_content(data, **descriptor(data)).evidence == "opaque_bytes"


@pytest.mark.parametrize("media,data", VALID_CONTAINERS, ids=["png", "jpeg", "gif", "webp", "webp-frame", "pdf", "zip"])
def test_signatures_alone_and_truncated_containers_do_not_pass(media, data):
    truncated = data.rstrip()[:-1] if media == "application/pdf" else data[:-1]
    for broken in (b"not this format", data[:6], truncated):
        with pytest.raises(AttachmentContentError):
            validate_attachment_content(broken, **descriptor(broken, media))


def test_png_crc_and_riff_size_are_verified():
    damaged_png = bytearray(png())
    damaged_png[29] ^= 1
    damaged_webp = bytearray(webp())
    damaged_webp[4] ^= 1
    for data, media in ((bytes(damaged_png), "image/png"), (bytes(damaged_webp), "image/webp")):
        with pytest.raises(AttachmentContentError):
            validate_attachment_content(data, **descriptor(data, media))


def test_bytes_digest_and_size_are_exact_and_quotas_remain_utf8_bytes():
    assert DEFAULT_ATTACHMENT_BYTES == 20 * 1024 * 1024
    data = "汉🧭".encode()
    for changes in ({"declared_bytes": len(data) - 1}, {"declared_sha256": "0" * 64}):
        with pytest.raises(AttachmentContentError) as error:
            validate_attachment_content(data, **(descriptor(data) | changes))
        assert error.value.code == "attachment_digest_mismatch" and error.value.status_code == 409
    with pytest.raises(AttachmentContentError) as too_large:
        validate_attachment_content(data, **descriptor(data), max_bytes=len(data) - 1)
    assert too_large.value.code == "content_too_large" and too_large.value.status_code == 413
    for changes in ({"declared_bytes": 0}, {"declared_bytes": True}, {"declared_sha256": "A" * 64}):
        with pytest.raises(AttachmentContentError):
            validate_attachment_content(data, **(descriptor(data) | changes))


@pytest.mark.parametrize("value", ["text/plain\r\nX-Injected: yes", "text/plain\0", "text/\x7fplain", "image/png; charset=utf-8",
    "text/plain; charset=latin-1", "text/plain; charset=utf-8; charset=utf-8", "text/plain; boundary=x", "x" * 257])
def test_media_header_injection_and_unknown_parameters_are_rejected(value):
    with pytest.raises(AttachmentContentError):
        normalize_attachment_media_type(value)


def test_media_normalization_header_match_and_unsupported_types():
    assert normalize_attachment_media_type(" Text/Plain ; CHARSET = \"UTF8\" ") == "text/plain"
    data = b"hello"
    assert validate_attachment_content(data, **descriptor(data, "TEXT/PLAIN; charset=utf-8"), upload_content_type="text/plain").media_type == "text/plain"
    with pytest.raises(AttachmentContentError):
        validate_attachment_content(data, **descriptor(data, "text/plain"), upload_content_type="application/octet-stream")
    with pytest.raises(AttachmentContentError) as unsupported:
        normalize_attachment_media_type("application/x-proprietary")
    assert unsupported.value.code == "capability_unsupported"


@pytest.mark.parametrize("name", ["", ".", "..", "../secret", "folder/file", r"folder\file", "C:secret", "name\r\nInjected: yes", "name\0", "x" * 256, "name\u0085"])
def test_filename_controls_and_path_names_cannot_enter_download_header(name):
    with pytest.raises(AttachmentContentError):
        attachment_content_disposition(name)


def test_content_disposition_is_ascii_rfc5987_without_raw_filename_interpolation():
    name = '汉字 🧭 "quoted"; %.txt'
    assert validate_attachment_name(name) == name
    header = attachment_content_disposition(name)
    assert header.isascii() and header.startswith('attachment; filename="attachment"; filename*=UTF-8\'\'')
    assert unquote(header.split("UTF-8''", 1)[1]) == name
    assert name not in header and "\r" not in header and "\n" not in header


class FakeCAS:
    scope_id, max_bytes = "attachment-scope", DEFAULT_ATTACHMENT_BYTES

    def __init__(self):
        self.data, self.calls = b"", []
        self.return_change, self.verify_change = {}, {}

    def put_bytes(self, data, *, kind="other", media_type="application/octet-stream"):
        self.calls.append("put")
        self.data = data
        digest = hashlib.sha256(data).hexdigest()
        reference = ArtifactRef(path=digest[:2] + "/" + digest, sha256=digest, size_bytes=len(data),
                                media_type=media_type, kind=kind, scope_id=self.scope_id, immutable=True)
        return reference.model_copy(update=self.return_change)

    def verify(self, reference):
        self.calls.append("verify")
        return reference.model_copy(update=self.verify_change)

    def read(self, _reference):
        self.calls.append("read")
        return self.data


def test_bridge_uses_actual_store_signatures_and_canonical_type():
    store, data = FakeCAS(), b"safe untrusted text"
    ref = put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data, "Text/Plain; charset=UTF-8"))
    assert ref.media_type == "text/plain" and ref.kind == "other" and ref.immutable
    assert read_attachment_content(store, ref, expected_scope=store.scope_id, **descriptor(data, "text/plain")) == data
    assert store.calls == ["put", "verify", "verify", "read"]


@pytest.mark.parametrize("change", [{"scope_id": "wrong"}, {"sha256": "0" * 64}, {"size_bytes": 99},
    {"immutable": False}, {"path": "unexpected/path"}, {"media_type": "text/plain"}, {"kind": "output"}])
def test_bad_returned_cas_reference_is_never_released(change):
    store, data = FakeCAS(), b"x"
    store.return_change = change
    with pytest.raises(AttachmentIntegrityError):
        put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data))


def test_bridge_revalidates_verify_result_and_read_bytes_before_return():
    store, data = FakeCAS(), b"x"
    reference = put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data))
    store.verify_change = {"size_bytes": True}  # Pydantic model_copy bypasses validation.
    with pytest.raises(AttachmentIntegrityError):
        read_attachment_content(store, reference, expected_scope=store.scope_id, **descriptor(data))
    store.verify_change = {}
    store.data = b"changed"
    with pytest.raises(AttachmentIntegrityError) as corrupt:
        read_attachment_content(store, reference, expected_scope=store.scope_id, **descriptor(data))
    assert corrupt.value.status_code == 503


def test_wrong_scope_and_insufficient_store_budget_fail_before_blob_io():
    store, data = FakeCAS(), b"abc"
    with pytest.raises(AttachmentIntegrityError):
        put_attachment_content(store, data, expected_scope="another-scope", **descriptor(data))
    store.max_bytes = 2
    with pytest.raises(AttachmentIntegrityError):
        put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data))
    assert store.calls == []


def test_actual_existing_platform_cas_roundtrip_and_corruption_detection(tmp_path):
    root = tmp_path / "private-cas"
    if os.name == "nt":
        from runtime_tests.test_windows_artifact_store import _private
        _private(root)
        backend = WindowsArtifactStore
    elif sys.platform.startswith("linux"):
        backend = LocalArtifactStore
    else:
        pytest.skip("existing Scope CAS has no admitted backend on this platform")
    data = "Actual platform CAS bytes 汉字🧭".encode()
    with backend(root, "attachment-scope", max_bytes=DEFAULT_ATTACHMENT_BYTES) as store:
        ref = put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data, "text/plain"))
        assert read_attachment_content(store, ref, expected_scope=store.scope_id, **descriptor(data, "text/plain")) == data
        assert put_attachment_content(store, data, expected_scope=store.scope_id, **descriptor(data, "text/plain")) == ref
        path = root / ref.path  # Server-issued immutable reference, not a client path.
        path.chmod(0o600)
        path.write_bytes(b"corrupted fixture")
        with pytest.raises(AttachmentIntegrityError):
            read_attachment_content(store, ref, expected_scope=store.scope_id, **descriptor(data, "text/plain"))
