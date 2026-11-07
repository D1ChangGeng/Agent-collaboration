"""Bounded attachment byte evidence and the existing admitted Scope CAS bridge.

This module grants no authorization and imports no URL or local path. The owning
service must finish its current upload/message ACL transaction before CAS I/O.
MIME evidence is encoding/container evidence, not a decoder, malware scan,
renderer or promise that HTML/SVG/Markdown is safe to execute. Downloads remain
untrusted bytes and use an attachment disposition.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from urllib.parse import quote
from xml.etree.ElementTree import ParseError, XMLPullParser

from runtime.models import ArtifactRef

DEFAULT_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_CONTAINER_RECORDS = 10_000
MAX_STRUCTURED_MARKS = 200_000
MAX_STRUCTURED_DEPTH = 64
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MEDIA = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+/[A-Za-z0-9!#$%&'*+.^_`|~-]+\Z")
_TEXT = frozenset({"text/plain", "text/markdown", "text/csv", "text/html"})
_BINARY = frozenset({"application/octet-stream", "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "application/zip"})


class AttachmentContentError(ValueError):
    def __init__(self, message, *, code="invalid_argument", status_code=400):
        super().__init__(message)
        self.code, self.status_code, self.message = code, status_code, message


class AttachmentIntegrityError(AttachmentContentError):
    def __init__(self):
        super().__init__("Attachment content integrity is unavailable.", code="attachment_content_unavailable", status_code=503)


@dataclass(frozen=True, slots=True)
class ValidatedAttachment:
    size_bytes: int
    sha256: str
    media_type: str
    evidence: str


def _bad_format():
    return AttachmentContentError("Attachment bytes do not match the declared media format.")


def _unsupported():
    return AttachmentContentError("Use application/octet-stream for this unsupported media format or structural complexity.",
                                  code="capability_unsupported", status_code=409)


def normalize_attachment_media_type(value):
    """Return lower-case base MIME. Only optional UTF-8 charset is supported.

UTF-8 charset may appear on text, JSON or SVG; it is verified and then omitted
from immutable metadata. Unknown parameters, non-UTF8 charsets, control bytes
and unsupported formats are rejected. Upload headers use these same rules.
"""
    if type(value) is not str or not 1 <= len(value) <= 256 or any(ord(char) < 32 or ord(char) >= 127 for char in value):
        raise AttachmentContentError("Invalid attachment media type.")
    parts = value.split(";")
    base = parts[0].strip().lower()
    if _MEDIA.fullmatch(base) is None:
        raise AttachmentContentError("Invalid attachment media type.")
    json_type = base == "application/json" or base.startswith("application/") and base.endswith("+json")
    textual = base in _TEXT or base == "image/svg+xml" or json_type
    if len(parts) > 2:
        raise AttachmentContentError("Unsupported attachment media parameters.")
    if len(parts) == 2:
        parameter = re.fullmatch(r'\s*charset\s*=\s*(?:"(utf-?8)"|(utf-?8))\s*', parts[1], re.IGNORECASE)
        if not textual or parameter is None:
            raise AttachmentContentError("Only UTF-8 attachment text is supported.")
    if base not in _BINARY and not textual:
        raise _unsupported()
    return base


def validate_attachment_name(name):
    """Display leaf name only; never a filesystem path or raw header value."""
    if (type(name) is not str or not name.strip() or len(name) > 255 or name in {".", ".."}
            or any(char in '/\\:' or unicodedata.category(char) in {"Cc", "Cs"} for char in name)):
        raise AttachmentContentError("Use a bounded attachment leaf name without path separators or controls.")
    return name


def attachment_content_disposition(name):
    name = validate_attachment_name(name)
    return "attachment; filename=\"attachment\"; filename*=UTF-8''" + quote(name, safe="", encoding="utf-8", errors="strict")


def _limits(declared_bytes, declared_sha256, max_bytes):
    if type(max_bytes) is not int or max_bytes < 1:
        raise AttachmentContentError("Invalid attachment byte budget.")
    if type(declared_bytes) is not int or declared_bytes < 1:
        raise AttachmentContentError("Attachment size must be a positive byte count.")
    if declared_bytes > max_bytes:
        raise AttachmentContentError("Attachment exceeds the configured byte limit.", code="content_too_large", status_code=413)
    if type(declared_sha256) is not str or _DIGEST.fullmatch(declared_sha256) is None:
        raise AttachmentContentError("Attachment SHA-256 must be lower-case hexadecimal.")


def _utf8(data):
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeError as error:
        raise _bad_format() from error
    if "\0" in text:
        raise _bad_format()
    return text


def _json_evidence(data):
    text = _utf8(data)
    quoted, escaped, depth, marks = False, False, 0, 0
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{}[]:,":
            marks += 1
            depth += (1 if char in "[{" else -1 if char in "]}" else 0)
            if marks > MAX_STRUCTURED_MARKS or depth > MAX_STRUCTURED_DEPTH:
                raise _unsupported()
    try:
        json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as error:
        raise _bad_format() from error


def _reject_json_constant(_value):
    raise ValueError("nonfinite JSON")


def _svg_evidence(data):
    text = _utf8(data)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise _bad_format()
    declaration = re.match(r"\s*<\?xml\b[^?]*\bencoding\s*=\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    if declaration is not None and declaration[1].lower() not in {"utf-8", "utf8"}:
        raise _bad_format()
    parser = XMLPullParser(events=("start", "end"))
    count, depth, root = 0, 0, None
    try:
        for start in range(0, len(data), 65536):
            parser.feed(data[start:start + 65536])
            for event, element in parser.read_events():
                if event == "start":
                    root = element.tag if root is None else root
                    count, depth = count + 1, depth + 1
                    if count > MAX_STRUCTURED_MARKS or depth > MAX_STRUCTURED_DEPTH:
                        raise _unsupported()
                else:
                    depth -= 1
                    element.clear()
        parser.close()
    except (ParseError, ValueError) as error:
        if isinstance(error, AttachmentContentError):
            raise
        raise _bad_format() from error
    if root not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
        raise _bad_format()


def _png(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _bad_format()
    offset, chunks, image_data = 8, 0, False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind, end = data[offset + 4:offset + 8], offset + 12 + length
        if end > len(data) or re.fullmatch(b"[A-Za-z]{4}", kind) is None:
            raise _bad_format()
        payload = data[offset + 8:end - 4]
        if zlib.crc32(data[offset + 4:end - 4]) != int.from_bytes(data[end - 4:end], "big"):
            raise _bad_format()
        chunks += 1
        if chunks > MAX_CONTAINER_RECORDS:
            raise _unsupported()
        if chunks == 1:
            if kind != b"IHDR" or length != 13:
                raise _bad_format()
            width, height, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if not 1 <= width <= 2**31 - 1 or not 1 <= height <= 2**31 - 1 or bits not in depths.get(color, set()) or compression or filtering or interlace not in {0, 1}:
                raise _bad_format()
        elif kind == b"IHDR":
            raise _bad_format()
        if kind == b"IDAT" and length:
            image_data = True
        if kind == b"IEND":
            if length or not image_data or end != len(data):
                raise _bad_format()
            return
        offset = end
    raise _bad_format()


def _jpeg(data):
    if not data.startswith(b"\xff\xd8"):
        raise _bad_format()
    offset, segments, frame, scan = 2, 0, False, False
    while offset < len(data):
        if data[offset] != 255:
            raise _bad_format()
        while offset < len(data) and data[offset] == 255:
            offset += 1
        if offset >= len(data):
            raise _bad_format()
        marker, offset = data[offset], offset + 1
        segments += 1
        if segments > MAX_CONTAINER_RECORDS:
            raise _unsupported()
        if marker == 217:
            if frame and scan and offset == len(data):
                return
            raise _bad_format()
        if marker in {0, 216} or 208 <= marker <= 215 or offset + 2 > len(data):
            raise _bad_format()
        length = int.from_bytes(data[offset:offset + 2], "big")
        end = offset + length
        if length < 2 or end > len(data):
            raise _bad_format()
        if marker in {192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207}:
            if length < 8:
                raise _bad_format()
            precision, height, width, components = struct.unpack(">BHHB", data[offset + 2:offset + 8])
            if not 2 <= precision <= 16 or not height or not width or not 1 <= components <= 4 or length != 8 + 3 * components:
                raise _bad_format()
            frame = True
        offset = end
        if marker == 218:
            if not frame or length < 6 or not 1 <= data[end - length + 2] <= 4 or length != 6 + 2 * data[end - length + 2]:
                raise _bad_format()
            scan = True
            while offset < len(data):
                found = data.find(b"\xff", offset)
                if found < 0 or found + 1 >= len(data):
                    raise _bad_format()
                following = data[found + 1]
                if following == 0 or 208 <= following <= 215:
                    offset = found + 2
                elif following == 255:
                    offset = found + 1
                else:
                    offset = found
                    break
    raise _bad_format()


def _gif(data):
    if len(data) < 14 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        raise _bad_format()
    width, height, packed = struct.unpack("<HHB", data[6:11])
    if not width or not height:
        raise _bad_format()
    offset, records, image = 13 + (3 * (2 ** ((packed & 7) + 1)) if packed & 128 else 0), 0, False

    def blocks(start):
        nonlocal records
        while start < len(data):
            size = data[start]
            start += 1
            records += 1
            if records > MAX_CONTAINER_RECORDS:
                raise _unsupported()
            if size == 0:
                return start
            start += size
            if start > len(data):
                raise _bad_format()
        raise _bad_format()

    while offset < len(data):
        tag, offset = data[offset], offset + 1
        if tag == 59 and image and offset == len(data):
            return
        if tag == 33:
            if offset >= len(data):
                raise _bad_format()
            offset = blocks(offset + 1)
        elif tag == 44:
            if offset + 9 > len(data):
                raise _bad_format()
            _left, _top, width, height, packed = struct.unpack("<HHHHB", data[offset:offset + 9])
            if not width or not height:
                raise _bad_format()
            offset += 9 + (3 * (2 ** ((packed & 7) + 1)) if packed & 128 else 0)
            if offset >= len(data) or not 2 <= data[offset] <= 8:
                raise _bad_format()
            offset, image = blocks(offset + 1), True
        else:
            raise _bad_format()
    raise _bad_format()


def _webp(data):
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP" or int.from_bytes(data[4:8], "little") != len(data) - 8:
        raise _bad_format()
    records = 0

    def chunks(start, stop, *, frame=False):
        nonlocal records
        image = False
        while start + 8 <= stop:
            kind = data[start:start + 4]
            size = int.from_bytes(data[start + 4:start + 8], "little")
            payload, end = start + 8, start + 8 + size
            records += 1
            if end + (size & 1) > stop or records > MAX_CONTAINER_RECORDS:
                raise _bad_format() if records <= MAX_CONTAINER_RECORDS else _unsupported()
            if size & 1 and data[end] != 0:
                raise _bad_format()
            if kind == b"VP8 ":
                if size < 10 or data[payload + 3:payload + 6] != b"\x9d\x01\x2a" or not (int.from_bytes(data[payload + 6:payload + 8], "little") & 16383) or not (int.from_bytes(data[payload + 8:payload + 10], "little") & 16383):
                    raise _bad_format()
                image = True
            elif kind == b"VP8L":
                if size < 5 or data[payload] != 47 or data[payload + 4] & 224:
                    raise _bad_format()
                image = True
            elif kind == b"VP8X":
                if frame or size != 10 or data[payload] & 193 or data[payload + 1:payload + 4] != b"\0\0\0":
                    raise _bad_format()
            elif kind == b"ANMF":
                if frame or size < 24 or not chunks(payload + 16, end, frame=True):
                    raise _bad_format()
                image = True
            start = end + (size & 1)
        if start != stop:
            raise _bad_format()
        return image

    if not chunks(12, len(data)):
        raise _bad_format()


def _pdf(data):
    if re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", data) is None:
        raise _bad_format()
    tail = re.search(rb"startxref\s+([0-9]{1,10})\s+%%EOF\s*\Z", data[-4096:])
    if tail is None:
        raise _bad_format()
    offset = int(tail[1])
    if offset >= len(data) or not (data[offset:offset + 4] == b"xref" or re.match(rb"[0-9]+\s+[0-9]+\s+obj\b", data[offset:offset + 128])):
        raise _bad_format()


def _zip(data):
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if eocd < 0 or eocd + 22 > len(data) or data[:4] not in {b"PK\x03\x04", b"PK\x05\x06"}:
        raise _bad_format()
    disk, directory_disk, disk_entries, entries, size, offset, comment = struct.unpack("<HHHHIIH", data[eocd + 4:eocd + 22])
    if disk or directory_disk or disk_entries != entries or entries == 65535 or size == 2**32 - 1 or offset == 2**32 - 1 or entries > MAX_CONTAINER_RECORDS:
        raise _unsupported()
    if eocd + 22 + comment != len(data) or offset + size != eocd:
        raise _bad_format()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            items = archive.infolist()  # No member read, extraction or decompression.
            if len(items) != entries:
                raise _bad_format()
            for item in items:
                start = item.header_offset
                if start < 0 or start + 30 > offset or data[start:start + 4] != b"PK\x03\x04":
                    raise _bad_format()
                name_size, extra_size = struct.unpack("<HH", data[start + 26:start + 30])
                if start + 30 + name_size + extra_size + item.compress_size > offset:
                    raise _bad_format()
    except (zipfile.BadZipFile, ValueError, UnicodeError, NotImplementedError) as error:
        if isinstance(error, AttachmentContentError):
            raise
        raise _bad_format() from error


def validate_attachment_content(data, *, declared_bytes, declared_sha256, media_type,
                                upload_content_type=None, max_bytes=DEFAULT_ATTACHMENT_BYTES):
    _limits(declared_bytes, declared_sha256, max_bytes)
    normalized = normalize_attachment_media_type(media_type)
    if upload_content_type is not None and normalize_attachment_media_type(upload_content_type) != normalized:
        raise AttachmentContentError("Upload Content-Type differs from the reserved media type.")
    if type(data) is not bytes:
        raise AttachmentContentError("Attachment content must be bytes.")
    if len(data) > max_bytes:
        raise AttachmentContentError("Attachment exceeds the configured byte limit.", code="content_too_large", status_code=413)
    if len(data) != declared_bytes or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), declared_sha256):
        raise AttachmentContentError("Attachment size or digest differs from the reservation.", code="attachment_digest_mismatch", status_code=409)
    if normalized == "application/octet-stream":
        evidence = "opaque_bytes"
    elif normalized in _TEXT:
        _utf8(data)
        evidence = "utf8_encoding"
    elif normalized == "image/svg+xml":
        _svg_evidence(data)
        evidence = "svg_xml_container"
    elif normalized == "application/json" or normalized.endswith("+json"):
        _json_evidence(data)
        evidence = "json_structure"
    else:
        {"image/png": _png, "image/jpeg": _jpeg, "image/gif": _gif, "image/webp": _webp,
         "application/pdf": _pdf, "application/zip": _zip}[normalized](data)
        evidence = "bounded_container"
    return ValidatedAttachment(len(data), declared_sha256, normalized, evidence)


def _store(store, expected_scope, declared_bytes):
    if (type(expected_scope) is not str or not expected_scope or getattr(store, "scope_id", None) != expected_scope
            or type(getattr(store, "max_bytes", None)) is not int or store.max_bytes < declared_bytes
            or any(not callable(getattr(store, name, None)) for name in ("put_bytes", "verify", "read"))):
        raise AttachmentIntegrityError()


def _ref(reference, *, expected_scope, declared_bytes, declared_sha256, media_type):
    try:
        if not isinstance(reference, ArtifactRef):
            raise TypeError("untyped reference")
        checked = ArtifactRef.model_validate(reference.model_dump(), strict=True)
        if (checked.model_dump() != reference.model_dump() or checked.immutable is not True or checked.scope_id != expected_scope
                or checked.size_bytes != declared_bytes or checked.sha256 != declared_sha256 or checked.media_type != media_type):
            raise ValueError("reference differs from immutable metadata")
        if checked.path != declared_sha256[:2] + "/" + declared_sha256:
            raise ValueError("reference is not the admitted CAS representation")
        return checked
    except (TypeError, ValueError) as error:
        raise AttachmentIntegrityError() from error


def _verify(store, reference, *, expected_scope, declared_bytes, declared_sha256, media_type):
    verified = _ref(store.verify(reference), expected_scope=expected_scope, declared_bytes=declared_bytes,
                    declared_sha256=declared_sha256, media_type=media_type)
    if verified != reference:
        raise AttachmentIntegrityError()


def put_attachment_content(store, data, *, expected_scope, declared_bytes, declared_sha256, media_type,
                           upload_content_type=None, max_bytes=DEFAULT_ATTACHMENT_BYTES):
    verified = validate_attachment_content(data, declared_bytes=declared_bytes, declared_sha256=declared_sha256,
        media_type=media_type, upload_content_type=upload_content_type, max_bytes=max_bytes)
    _store(store, expected_scope, verified.size_bytes)
    try:
        reference = store.put_bytes(data, kind="other", media_type=verified.media_type)
        checked = _ref(reference, expected_scope=expected_scope, declared_bytes=declared_bytes,
                       declared_sha256=declared_sha256, media_type=verified.media_type)
        if checked.kind != "other":
            raise AttachmentIntegrityError()
        _verify(store, checked, expected_scope=expected_scope, declared_bytes=declared_bytes,
                declared_sha256=declared_sha256, media_type=verified.media_type)
        return checked
    except AttachmentIntegrityError:
        raise
    except Exception as error:
        raise AttachmentIntegrityError() from error


def read_attachment_content(store, reference, *, expected_scope, declared_bytes, declared_sha256, media_type,
                            max_bytes=DEFAULT_ATTACHMENT_BYTES):
    _limits(declared_bytes, declared_sha256, max_bytes)
    normalized = normalize_attachment_media_type(media_type)
    _store(store, expected_scope, declared_bytes)
    checked = _ref(reference, expected_scope=expected_scope, declared_bytes=declared_bytes,
                   declared_sha256=declared_sha256, media_type=normalized)
    try:
        _verify(store, checked, expected_scope=expected_scope, declared_bytes=declared_bytes,
                declared_sha256=declared_sha256, media_type=normalized)
        data = store.read(checked)
        validate_attachment_content(data, declared_bytes=declared_bytes, declared_sha256=declared_sha256,
                                    media_type=normalized, max_bytes=max_bytes)
        return data
    except AttachmentIntegrityError:
        raise
    except Exception as error:
        raise AttachmentIntegrityError() from error
