# tests/test_render_zenodo.py
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from works.models import Work, Source


class RenderZenodoTest(TestCase):
    def setUp(self):
        # Temp “project root”
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.templates_dir = self.project_root / "works" / "templates"
        self.cmds_dir = self.project_root / "works" / "management" / "commands"
        self.data_dir = self.project_root / "data"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.cmds_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Minimal README template with Sources
        (self.templates_dir / "README.md.j2").write_text(
            "# OPTIMAP FAIR Data Package\n"
            "**Version:** {{ version }}\n\n"
            "## Sources\n\n"
            "{% for src in sources %}- [{{ src.name }}]({{ src.url }})\n{% endfor %}\n"
            "\n## Codebook\n\n"
            "| Field | Description |\n|---|---|\n| id | pk |\n",
            encoding="utf-8",
        )

        # DB fixtures
        Work.objects.create(title="A", publicationDate="2010-10-10")

        # Bad labels to clean
        Source.objects.create(name="2000", url_field="https://optimap.science")  # numeric-only -> OPTIMAP
        Source.objects.create(name="",     url_field="https://example.org")      # blank -> domain label
        Source.objects.create(name=" ",    url_field="https://example.org")      # duplicate -> dedupe

        # Good label
        Source.objects.create(
            name="AGILE: GIScience Series",
            url_field="https://agile-giss.copernicus.org"
        )

        # Import zenodo module after DB is ready
        import importlib
        self.zenodo_mod = importlib.import_module("works.zenodo")

        # Fake Path so resolve() stays inside tmp root
        class FakePath(Path):
            _flavour = Path(".")._flavour
            def resolve(self):
                return self
        self.FakePath = FakePath
        self.zenodo_file = str(self.project_root / "works" / "zenodo.py")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_render_produces_clean_readme_and_assets(self):
        # Don't actually run `git archive`
        def _noop(*a, **k): return None

        with patch.object(self.zenodo_mod, "__file__", new=self.zenodo_file), \
             patch.object(self.zenodo_mod, "Path", self.FakePath), \
             patch("subprocess.run", _noop):
            call_command("render_zenodo")

        readme_path = self.data_dir / "README.md"
        zip_path    = self.data_dir / "optimap-main.zip"
        dyn_path    = self.data_dir / "zenodo_dynamic.json"

        self.assertTrue(readme_path.exists(), "README.md not generated")
        self.assertTrue(zip_path.exists(), "optimap-main.zip not generated")
        self.assertTrue(dyn_path.exists(), "zenodo_dynamic.json not generated")

        md = readme_path.read_text(encoding="utf-8")
        # Sources cleanup assertions
        self.assertNotIn("- [2000](", md, "Numeric-only label leaked into Sources")
        self.assertIn("- [OPTIMAP](https://optimap.science)", md, "OPTIMAP override missing")
        self.assertIn("AGILE: GIScience Series", md, "Named source missing")
        # example.org should appear only once after dedupe
        self.assertEqual(md.count("example.org"), 1, "Duplicate source/domain not deduped")
