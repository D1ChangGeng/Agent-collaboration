"""Trusted composition policy for Host-owned attachment materialization ports.

This registry is not a message field or an advertised remote claim. The owning
Runtime installs a specific endpoint only alongside its actual Native Host
attachment port. Other endpoints retain the default denial.
"""
from __future__ import annotations


def native_attachment_delivery_supported(authority, endpoint_id):
    installed = getattr(authority, "_native_attachment_delivery_endpoints", None)
    return (isinstance(installed, (set, frozenset))
            and isinstance(endpoint_id, str) and endpoint_id in installed)
