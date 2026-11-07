"""Packaged Client 1 DTO contracts; validation grants no identity or authority.

The schema adopts the development pack's static machine contract with the
recorded timestamp and advertised attachment-limit corrections. It is shipped in
the Runtime package, not retrieved from the RFC workspace or the network. The
HTTP/Domain layer still owns authorization, UTF-8 budgets, quotas, transactions
and evidence provenance; a schema-valid DTO alone proves none of those facts.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

SCHEMA_FILE = Path(__file__).with_name("client_models.schema.json")
DRAFT = "https://json-schema.org/draft/2020-12/schema"
MAX_SCHEMA_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_JSON_NODES = 100_000
MAX_JSON_DEPTH = 64
MODEL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
RFC3339 = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
                     r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z")
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, OverflowError))
def _timestamp(value):
    # jsonschema's date-time checker is an optional extra and is absent in the
    # base installation. Enforce the Runtime's aware RFC3339 representation
    # explicitly instead of silently accepting arbitrary strings.
    if not isinstance(value, str):
        return True  # The selected JSON Schema owns its value's type.
    if not RFC3339.fullmatch(value):
        return False
    value = value[:-1] + "+00:00" if value[-1:] in {"Z", "z"} else value
    parsed = datetime.fromisoformat(value)
    return parsed.utcoffset() is not None


class ClientContractSourceError(RuntimeError):
    code = "client_contract_source_invalid"


class ClientContractViolation(ValueError):
    """A redacted failure safe for an ingress error mapper to describe."""

    code = "invalid_contract"

    def __init__(self, model_name, path=(), keyword="schema"):
        self.model_name = model_name
        self.path = tuple(path)
        self.keyword = keyword
        # Caller-controlled property names/values are deliberately excluded.
        super().__init__(f"{model_name} failed its client contract ({keyword})")


def _deny_retrieval(uri):
    raise NoSuchResource(ref=uri)


def _json_bound(value):
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("JSON complexity limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object key type")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("non-finite JSON number")
        elif item is not None and type(item) not in {str, int, bool}:
            raise ValueError("non-JSON value")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("JSON byte limit")
    return encoded


def _safe_document(document):
    """Reject resolution extensions before a validator could retrieve anything."""
    if (not isinstance(document, dict) or document.get("$schema") != DRAFT
            or not isinstance(document.get("$defs"), dict) or not document["$defs"]):
        raise ClientContractSourceError("client schema does not declare Draft 2020-12 models")
    definitions = document["$defs"]
    if any(not MODEL_NAME.fullmatch(name) for name in definitions):
        raise ClientContractSourceError("client schema model identity is invalid")
    references = {name: set() for name in definitions}
    count = 0
    for name, definition in definitions.items():
        pending = [(definition, 0)]
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
                raise ClientContractSourceError("client schema complexity exceeds bound")
            if isinstance(item, dict):
                if any(key.startswith("$") and key.lower().endswith("ref") and key != "$ref" for key in item):
                    raise ClientContractSourceError("client schema resolution extension is unsupported")
                if "$ref" in item:
                    reference = item["$ref"]
                    if (not isinstance(reference, str) or not reference.startswith("#/$defs/")
                            or reference.removeprefix("#/$defs/") not in definitions):
                        raise ClientContractSourceError("client schema references must name a packaged local model")
                    references[name].add(reference.removeprefix("#/$defs/"))
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)

    def acyclic(name, ancestors, checked):
        if name in ancestors:
            raise ClientContractSourceError("recursive client schema requires explicit supported evolution")
        if name in checked:
            return
        for referred in references[name]:
            acyclic(referred, ancestors | {name}, checked)
        checked.add(name)

    checked = set()
    for name in references:
        acyclic(name, set(), checked)
    try:
        Draft202012Validator.check_schema(document)
    except Exception as error:
        raise ClientContractSourceError("packaged client schema is invalid") from error
    return document


@lru_cache(maxsize=1)
def _document():
    try:
        with SCHEMA_FILE.open("rb") as stream:
            raw = stream.read(MAX_SCHEMA_BYTES + 1)
        if len(raw) > MAX_SCHEMA_BYTES:
            raise ClientContractSourceError("packaged client schema exceeds bound")
        return _safe_document(json.loads(raw))
    except (OSError, ValueError) as error:
        raise ClientContractSourceError("packaged client schema is unavailable") from error


def _model_schema(document, model_name):
    if not isinstance(model_name, str) or model_name not in document["$defs"]:
        raise ClientContractSourceError("client model is not in the packaged contract")
    return {"$schema": DRAFT, "$id": document["$id"], "$defs": document["$defs"],
            "$ref": "#/$defs/" + model_name}


@lru_cache(maxsize=128)
def _validator(model_name):
    selected = _model_schema(_document(), model_name)
    resource = DRAFT202012.create_resource(selected)
    registry = Registry(retrieve=_deny_retrieval).with_resource(selected["$id"], resource)
    return Draft202012Validator(selected, format_checker=FORMATS, registry=registry)


class ClientContracts:
    """Reusable static contract registry; every returned object is caller-owned."""

    @property
    def model_names(self):
        return tuple(_document()["$defs"])

    def schema(self, model_name):
        return deepcopy(_model_schema(_document(), model_name))

    def validate(self, model_name, json_value):
        validator = _validator(model_name)
        try:
            value = json.loads(_json_bound(json_value))
        except (ValueError, TypeError, UnicodeError, RecursionError) as error:
            raise ClientContractViolation(model_name, keyword="json_resource_limit") from error
        failure = next(validator.iter_errors(value), None)
        if failure is not None:
            raise ClientContractViolation(model_name, failure.absolute_path, str(failure.validator))
        return value
