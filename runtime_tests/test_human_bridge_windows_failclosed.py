from __future__ import annotations

# ruff: noqa: I001 -- standalone candidate and repository classify local imports differently.

import pytest

from runtime import human_bridge_file_provider as provider
from runtime.human_bridge_file_provider import LocalHumanBridgeTransport, ProviderRejected


def test_windows_profile_requires_separate_reparse_and_acl_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(provider, "IS_POSIX", False)
    with pytest.raises(ProviderRejected, match="requires POSIX"):
        LocalHumanBridgeTransport(tmp_path / "provider")
