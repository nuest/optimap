# tests/test_deposit_zenodo.py
import json
import tempfile
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, override_settings
from works.models import Work, Source
from works.zenodo import _build_upload_list, _latest_dump_files


class BuildUploadListTest(SimpleTestCase):
    """Direct unit tests for the upload-list helpers (issue #63, item 4)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.data_dir = self.root / "data"
        self.dump_dir = self.root / "optimap_cache"
        self.data_dir.mkdir()
        self.dump_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_latest_dump_files_picks_newest_timestamp_only(self):
        # Two cycles in the same dir, three formats each
        for ts in ("20240101", "20250101"):
            (self.dump_dir / f"optimap_data_dump_{ts}.geojson").write_text("{}")
            (self.dump_dir / f"optimap_data_dump_{ts}.geojson.gz").write_bytes(b"\x1f\x8b")
            (self.dump_dir / f"optimap_data_dump_{ts}.gpkg").write_bytes(b"GPKG")
        # And a CSV pair for the newer cycle only
        (self.dump_dir / "optimap_data_dump_20250101.csv").write_text("a,b\n")
        (self.dump_dir / "optimap_data_dump_20250101.csv.gz").write_bytes(b"\x1f\x8b")

        files = _latest_dump_files(self.dump_dir)
        names = {p.name for p in files}
        self.assertEqual(names, {
            "optimap_data_dump_20250101.geojson",
            "optimap_data_dump_20250101.geojson.gz",
            "optimap_data_dump_20250101.gpkg",
            "optimap_data_dump_20250101.csv",
            "optimap_data_dump_20250101.csv.gz",
        })

    def test_build_upload_list_includes_csv_variants(self):
        (self.data_dir / "README.md").write_text("# x")
        (self.data_dir / "optimap-main.zip").write_bytes(b"ZIP")
        for ext in ("geojson", "geojson.gz", "gpkg", "csv", "csv.gz"):
            (self.data_dir / f"optimap_data_dump_20250101.{ext}").write_bytes(b"x")

        paths = _build_upload_list(self.data_dir, dump_dir=self.dump_dir)
        names = {p.name for p in paths}

        # README + git archive snapshot
        self.assertIn("README.md", names)
        self.assertIn("optimap-main.zip", names)
        # All five dump formats land in the upload
        for ext in ("geojson", "geojson.gz", "gpkg", "csv", "csv.gz"):
            self.assertIn(f"optimap_data_dump_20250101.{ext}", names)

    def test_build_upload_list_falls_back_to_dump_dir_when_data_dir_has_no_dumps(self):
        """Production layout: render writes to data/, regenerate writes to cache."""
        (self.data_dir / "README.md").write_text("# x")
        (self.data_dir / "optimap-main.zip").write_bytes(b"ZIP")
        # Dumps only in dump_dir
        for ext in ("geojson", "gpkg", "csv"):
            (self.dump_dir / f"optimap_data_dump_20250101.{ext}").write_bytes(b"x")

        paths = _build_upload_list(self.data_dir, dump_dir=self.dump_dir)
        names = {p.name for p in paths}
        self.assertIn("README.md", names)
        self.assertIn("optimap_data_dump_20250101.geojson", names)
        self.assertIn("optimap_data_dump_20250101.gpkg", names)
        self.assertIn("optimap_data_dump_20250101.csv", names)


class DepositZenodoTest(TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.templates_dir = self.project_root / "works" / "templates"
        self.cmds_dir = self.project_root / "works" / "management" / "commands"
        self.data_dir = self.project_root / "data"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.cmds_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Minimal README so description→HTML works
        (self.data_dir / "README.md").write_text("# Title\n\nSome text.", encoding="utf-8")
        (self.data_dir / "optimap-main.zip").write_bytes(b"ZIP")
        # dynamic JSON with new related identifiers and version
        (self.data_dir / "zenodo_dynamic.json").write_text(json.dumps({
            "title": "OPTIMAP FAIR Data Package (test)",
            "version": "v999",
            "related_identifiers": [
                {"relation": "describes", "identifier": "https://optimap.science", "scheme": "url"}
            ]
        }), encoding="utf-8")

        # Fake dump files to upload
        (self.data_dir / "optimap_data_dump_20250101.geojson").write_text("{}", encoding="utf-8")
        (self.data_dir / "optimap_data_dump_20250101.gpkg").write_bytes(b"GPKG")

        # Minimal DB so import paths work
        Work.objects.create(title="A", publicationDate="2010-10-10")
        Source.objects.create(name="OPTIMAP", url_field="https://optimap.science")

        # Import zenodo module
        import importlib
        self.zenodo_mod = importlib.import_module("works.zenodo")

        class FakePath(Path):
            _flavour = Path(".")._flavour
            def resolve(self):
                return self
        self.FakePath = FakePath
        self.zenodo_file = str(self.project_root / "works" / "zenodo.py")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_deposit_merges_metadata_and_uses_zenodo_client_for_uploads(self):
        # Fake Zenodo deposition (existing metadata)
        existing = {
            "submitted": False,
            "state": "unsubmitted",
            "links": {"edit": "http://edit", "bucket": "http://bucket"},
            "metadata": {
                "title": "Existing Title",
                "upload_type": "dataset",
                "publication_date": "2025-07-14",
                "creators": [{"name": "OPTIMAP"}],
                "keywords": ["Open Science"],
                "related_identifiers": [
                    {"relation": "isSupplementTo", "identifier": "https://old.example", "scheme": "url"}
                ],
                "language": "eng",
                "description": "<p>Old</p>",
                "version": "v1",
            },
        }

        put_payload = {}

    def _fake_get(url, params=None, **kwargs):
        class R:
            status_code = 200
            text = "ok"
            def json(self):
                # whatever object your test expects (e.g., deepcopy(existing))
                return deepcopy(existing)
            def raise_for_status(self):
                return None
        return R()

    def _fake_post(url, params=None, json=None, **kwargs):
        class R:
            status_code = 200
            text = "ok"
            def json(self):
                # return what your code reads from POST responses, if anything
                return {"links": {"bucket": "https://example-bucket"}}
            def raise_for_status(self):
                return None
        return R()

    def _fake_put(url, params=None, data=None, headers=None, **kwargs):
        class R:
            status_code = 200
            text = "ok"
            def raise_for_status(self):
                return None
        return R()

        uploaded = {}

        # zenodo-client upload shim: capture files that would be uploaded
        def _fake_update_zenodo(deposition_id, paths, sandbox=True, access_token=None, publish=False):
            self.assertEqual(deposition_id, "123456")
            self.assertTrue(sandbox)
            self.assertEqual(access_token, "tok")
            names = {Path(p).name for p in paths}
            self.assertIn("README.md", names)
            self.assertIn("optimap-main.zip", names)
            self.assertTrue(any(n.endswith(".geojson") for n in names))
            self.assertTrue(any(n.endswith(".gpkg") for n in names))
            uploaded["paths"] = [str(p) for p in paths]
            class R:
                def json(self): return {"links": {"html": f"https://sandbox.zenodo.org/deposit/{deposition_id}"}}
            return R()

        # Mock Zenodo client
        mock_zenodo = type('MockZenodo', (), {
            'access_token': None,
            'update': lambda *args, **kwargs: _fake_update_zenodo(**kwargs)
        })()

        with patch.object(self.zenodo_mod, "__file__", new=self.zenodo_file), \
             patch.object(self.zenodo_mod, "Path", self.FakePath), \
             patch.object(self.zenodo_mod.requests, "get", _fake_get), \
             patch.object(self.zenodo_mod.requests, "put", _fake_put), \
             patch.object(self.zenodo_mod.requests, "delete", lambda *a, **k: type('R', (), {'status_code': 204})()), \
             patch.object(self.zenodo_mod, "Zenodo", return_value=mock_zenodo), \
             patch.object(self.zenodo_mod, "_markdown_to_html", lambda s: "<p>HTML</p>"), \
             override_settings(ZENODO_UPLOADS_ENABLED=True, ZENODO_API_TOKEN="tok", ZENODO_SANDBOX_DEPOSITION_ID="123456"):

            call_command(
                "deposit_zenodo",
                "--deposition-id", "123456",
            )

        # Merged metadata: required fields preserved, description/version updated, related merged
        merged = put_payload["metadata"]
        self.assertEqual(merged["title"], "Existing Title")
        self.assertEqual(merged["upload_type"], "dataset")
        self.assertEqual(merged["publication_date"], "2025-07-14")
        self.assertEqual(merged["creators"], [{"name": "OPTIMAP"}])

        self.assertIn("description", merged)
        self.assertTrue(merged["description"].startswith("<p"))  # from markdown->HTML

        self.assertIsInstance(merged.get("version"), str)
        rel = {(d["identifier"], d["relation"]) for d in merged.get("related_identifiers", [])}
        self.assertIn(("https://old.example", "isSupplementTo"), rel)
        self.assertIn(("https://optimap.science", "describes"), rel)

        # Uploader called with expected files
        self.assertIn("paths", uploaded)
        self.assertGreater(len(uploaded["paths"]), 0)

    def test_doi_fields_are_protected_from_overwrite(self):
        """Test that DOI and prereserve_doi fields are never overwritten."""
        # Existing deposition with reserved DOI
        existing_with_doi = {
            "submitted": False,
            "state": "unsubmitted",
            "links": {"edit": "http://edit", "bucket": "http://bucket"},
            "metadata": {
                "title": "Test Title",
                "upload_type": "dataset",
                "publication_date": "2025-01-01",
                "creators": [{"name": "Test Author"}],
                "doi": "10.5072/zenodo.123456",
                "prereserve_doi": {"doi": "10.5072/zenodo.123456", "recid": 123456},
                "version": "v1",
                "description": "<p>Old description</p>",
            },
        }

        captured_metadata = {}

        def _fake_get(url, params=None, **kwargs):
            class R:
                status_code = 200
                text = "ok"
                def json(self):
                    return deepcopy(existing_with_doi)
                def raise_for_status(self):
                    return None
            return R()

        def _fake_put(url, params=None, data=None, headers=None, **kwargs):
            # Capture the metadata that would be sent to Zenodo
            if data:
                captured_metadata.update(json.loads(data))
            class R:
                status_code = 200
                text = "ok"
                def raise_for_status(self):
                    return None
            return R()

        def _fake_update_zenodo(deposition_id, paths, sandbox=True, access_token=None, publish=False):
            class R:
                def json(self):
                    return {"links": {"html": "https://sandbox.zenodo.org/deposit/123456"}}
            return R()

        # Create dynamic JSON that tries to include a DOI (should be ignored)
        (self.data_dir / "zenodo_dynamic.json").write_text(json.dumps({
            "title": "NEW TITLE (should be ignored)",
            "version": "v999",
            "doi": "10.9999/fake.doi",  # This should be removed before merging
            "prereserve_doi": {"doi": "10.9999/fake.doi", "recid": 999},  # This too
            "description": "New description",
        }), encoding="utf-8")

        # Mock Zenodo client
        mock_zenodo2 = type('MockZenodo', (), {
            'access_token': None,
            'update': lambda *args, **kwargs: _fake_update_zenodo(**kwargs)
        })()

        with patch.object(self.zenodo_mod, "__file__", new=self.zenodo_file), \
             patch.object(self.zenodo_mod, "Path", self.FakePath), \
             patch.object(self.zenodo_mod.requests, "get", _fake_get), \
             patch.object(self.zenodo_mod.requests, "put", _fake_put), \
             patch.object(self.zenodo_mod.requests, "delete", lambda *a, **k: type('R', (), {'status_code': 204})()), \
             patch.object(self.zenodo_mod, "Zenodo", return_value=mock_zenodo2), \
             patch.object(self.zenodo_mod, "_markdown_to_html", lambda s: "<p>Updated</p>"), \
             override_settings(
                 ZENODO_UPLOADS_ENABLED=True,
                 ZENODO_API_TOKEN="test_token",
                 ZENODO_API_BASE="https://sandbox.zenodo.org/api"
             ):

            call_command(
                "deposit_zenodo",
                "--deposition-id", "123456",
                "--token", "test_token",
            )

        # Verify captured metadata
        merged = captured_metadata.get("metadata", {})

        # DOI should be preserved from existing (not overwritten)
        self.assertEqual(merged.get("doi"), "10.5072/zenodo.123456",
                        "DOI should be preserved from existing deposition")
        self.assertNotEqual(merged.get("doi"), "10.9999/fake.doi",
                           "DOI should NOT be overwritten by incoming data")

        # prereserve_doi should also be preserved
        self.assertEqual(merged.get("prereserve_doi", {}).get("doi"), "10.5072/zenodo.123456",
                        "prereserve_doi should be preserved")

        # Non-DOI fields should be updated from incoming data (no longer protected)
        self.assertEqual(merged["title"], "NEW TITLE (should be ignored)",
                        "Title should be updated from incoming data")
        self.assertEqual(merged["upload_type"], "dataset",
                        "upload_type should be present")

        # Version and description should be updated
        self.assertEqual(merged["version"], "v999",
                        "Version should be updated (in default patch list)")
        self.assertIn("<p>Updated</p>", merged.get("description", ""),
                     "Description should be updated (in default patch list)")
