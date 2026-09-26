from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(sys.version_info < (3, 12), "Runtime release tools require Python 3.12+")
class ReleaseToolTests(unittest.TestCase):
    def test_release_payload_scope(self):
        tool = load("build_release", "build_release.py")
        self.assertTrue(tool.included("runtime/project_entry.py"))
        self.assertTrue(tool.included("docs/runtime/skills/acs-runtime-model/SKILL.md"))
        self.assertTrue(tool.included("assets/acs-mark.svg"))
        self.assertFalse(tool.included(".agents/manifest.json"))
        self.assertFalse(tool.included(".tmp/private.json"))
        self.assertFalse(tool.included("runtime/__pycache__/module.pyc"))

    def test_doctor_redacts_backend_failure(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        with mock.patch.dict("sys.modules", {"runtime.project_service": None}):
            observed = doctor.runtime_readback(Path("missing"), Path("missing"), "root_manager")
        self.assertEqual(observed, {"state": "unavailable", "reason": "runtime_readback_failed"})

    def test_doctor_uses_configured_source_provider_for_project_context(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        import sys
        from types import SimpleNamespace

        configured = SimpleNamespace(
            artifact_configs=lambda: [
                SimpleNamespace(scope_id="local-scope", authorized_source_roots=("/source",))
            ],
            credential=lambda: "private-credential",
        )
        service = SimpleNamespace(
            authenticate=lambda credential: None,
            authority=SimpleNamespace(_artifact_store=object()),
        )
        source = mock.Mock()
        project = mock.Mock()
        project.execute.side_effect = [
            ("observed", {"connection_state": "authorized", "profile": "root_manager",
                          "grant": {"ref": "grant:root"}}, []),
            ("observed", {"items": [{"project_id": "project-alpha"}]}, []),
            ("current", {"root_handle": "project:project-alpha:root",
                         "context_completeness": "current"}, []),
        ]
        project.available_tools.return_value = ["load_project"]
        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "catalog.json"
            catalog.write_text("{}")
            context = mock.MagicMock()
            context.__enter__.return_value = (service, configured)
            with (
                mock.patch.dict(sys.modules, {
                    "runtime.project_source": SimpleNamespace(ProjectSources=mock.Mock(return_value=source)),
                    "runtime.project_service": SimpleNamespace(ProjectService=mock.Mock(return_value=project)),
                    "runtime.surface_config": SimpleNamespace(configured_service=mock.Mock(return_value=context)),
                }),
            ):
                result = doctor.runtime_readback(Path(td) / "config.json", catalog, "root_manager")
        self.assertEqual(result["project_contexts"][0]["context_completeness"], "current")
        self.assertEqual(result["tools"], ["load_project"])
        source.close.assert_called_once()

    def test_install_preview_is_read_only_when_docker_missing(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        import sys

        with mock.patch.dict(sys.modules, {"acs_doctor": doctor}):
            installer = load("acs_install", "acs_install.py")
        readiness = {
            "source_backend": {"available": False},
            "tools": {
                "git": {"available": True},
                "uv": {"available": True},
                "docker": {"available": False},
            },
        }
        with (
            mock.patch.object(installer, "inspect", return_value=readiness),
            mock.patch.object(installer, "run", side_effect=AssertionError("mutation")),
        ):
            result = installer.install(
                harnesses=["codex"], project=None, project_id=None, apply=False
            )
        self.assertEqual(result["state"], "planned")
        self.assertFalse(result["prerequisites"]["docker"])

    def test_apply_refuses_host_without_source_backend(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        with mock.patch.dict(sys.modules, {"acs_doctor": doctor}):
            installer = load("acs_install", "acs_install.py")
        readiness = {
            "source_backend": {"available": False},
            "tools": {name: {"available": True} for name in ("git", "uv", "docker")},
        }
        with (
            mock.patch.object(installer, "inspect", return_value=readiness),
            mock.patch.object(installer, "run", side_effect=AssertionError("mutation")),
            self.assertRaisesRegex(ValueError, "Source/CAS"),
        ):
            installer.install(harnesses=["codex"], project=None, project_id=None, apply=True)

    def test_provider_password_is_private_and_idempotent(self):
        doctor = load("acs_doctor", "acs_doctor.py")
        import sys

        with mock.patch.dict(sys.modules, {"acs_doctor": doctor}):
            installer = load("acs_install", "acs_install.py")
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.object(installer, "private_root", return_value=Path(td)),
        ):
            path, first = installer.local_provider_environment()
            again, second = installer.local_provider_environment()
            self.assertEqual(path, again)
            self.assertEqual(first["ACS_POSTGRES_PASSWORD"], second["ACS_POSTGRES_PASSWORD"])
            self.assertGreater(len(first["ACS_POSTGRES_PASSWORD"]), 32)
            self.assertEqual(
                json.loads(path.read_text())["schema_version"], "acs-local-providers/1"
            )


if __name__ == "__main__":
    unittest.main()
