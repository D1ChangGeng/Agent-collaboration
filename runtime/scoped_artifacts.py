"""Explicit Scope-to-CAS routing; no default store and no filesystem search."""
from __future__ import annotations

from runtime.artifacts import ArtifactError
from runtime.models import ArtifactRef


class ScopedArtifactStores:
    def __init__(self, stores):
        self._stores = {}
        roots = []
        for store in stores:
            if store.scope_id in self._stores:
                raise ArtifactError("duplicate artifact Scope")
            root = store.root.resolve()
            if any(root == old or root.is_relative_to(old) or old.is_relative_to(root) for old in roots):
                raise ArtifactError("artifact Scope roots must be disjoint")
            roots.append(root)
            self._stores[store.scope_id] = store
        if not self._stores:
            raise ArtifactError("an explicit artifact store registry is required")

    def for_scope(self, scope_id):
        try:
            return self._stores[scope_id]
        except KeyError:
            raise ArtifactError("artifact Scope has no admitted provider") from None

    def read(self, reference):
        if not isinstance(reference, ArtifactRef):
            raise ArtifactError("a complete typed artifact reference is required")
        return self.for_scope(reference.scope_id).read(reference)

    def verify(self, reference):
        if not isinstance(reference, ArtifactRef):
            raise ArtifactError("a complete typed artifact reference is required")
        return self.for_scope(reference.scope_id).verify(reference)
