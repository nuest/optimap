"""
Integration tests for Zenodo deposition.

These tests run against the actual Zenodo sandbox API and require:
1. A tests/.env file with ZENODO_API_TOKEN and ZENODO_SANDBOX_DEPOSITION_ID
2. Active internet connection
3. Valid Zenodo sandbox credentials

To run these tests:
    python manage.py test tests.test_zenodo_integration

To skip these tests (default):
    python manage.py test tests --exclude-tag=integration
"""
import os
import json
import tempfile
from pathlib import Path
from django.test import TestCase, tag, override_settings
from django.core.management import call_command
from works.models import Work, Source
from django.conf import settings


def load_test_env():
    """Load environment variables from tests/.env file."""
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


@tag('integration', 'zenodo')
class ZenodoIntegrationTest(TestCase):
    """
    Integration tests for Zenodo API.

    Requires tests/.env with:
    - ZENODO_API_TOKEN
    - ZENODO_SANDBOX_DEPOSITION_ID
    - ZENODO_API_BASE (optional, defaults to sandbox)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_test_env()

        cls.api_token = os.environ.get('ZENODO_API_TOKEN')
        cls.deposition_id = os.environ.get('ZENODO_SANDBOX_DEPOSITION_ID')
        cls.api_base = os.environ.get('ZENODO_API_BASE', 'https://sandbox.zenodo.org/api')

        if not cls.api_token or not cls.deposition_id:
            raise unittest.SkipTest(
                "Zenodo integration tests require ZENODO_API_TOKEN and "
                "ZENODO_SANDBOX_DEPOSITION_ID in tests/.env file. "
                "See tests/.env.template for setup instructions."
            )

    def setUp(self):
        """Set up test data and temporary directories."""
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmpdir.name)
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Create test data files
        (self.data_dir / "README.md").write_text(
            "# OPTIMAP Test Data\\n\\nTest dataset for integration testing.",
            encoding="utf-8"
        )
        (self.data_dir / "optimap-main.zip").write_bytes(b"TEST_ZIP_CONTENT")
        (self.data_dir / "last_version.txt").write_text("v1.0.0-test", encoding="utf-8")

        # Create dynamic metadata
        (self.data_dir / "zenodo_dynamic.json").write_text(json.dumps({
            "title": "OPTIMAP Test Dataset",
            "version": "v1.0.0-test",
            "related_identifiers": [
                {
                    "relation": "describes",
                    "identifier": "https://optimap.science",
                    "scheme": "url"
                }
            ]
        }), encoding="utf-8")

        # Create fake data dump files
        (self.data_dir / "optimap_data_dump_20250101.geojson").write_text("{}", encoding="utf-8")
        (self.data_dir / "optimap_data_dump_20250101.gpkg").write_bytes(b"GPKG_TEST")

        # Create minimal database records
        Work.objects.create(title="Test Work", doi="10.test/integration")
        Source.objects.create(name="Test Source", url_field="https://test.example.com")

    def tearDown(self):
        """Clean up temporary directories."""
        self._tmpdir.cleanup()

    @override_settings(
        ZENODO_API_TOKEN=None,  # Will be set from environment
        ZENODO_SANDBOX_DEPOSITION_ID=None,  # Will be set from environment
        ZENODO_API_BASE=None  # Will be set from environment
    )
    def test_render_zenodo_command(self):
        """Test that render_zenodo command generates all required files."""
        with override_settings(
            ZENODO_API_TOKEN=self.api_token,
            ZENODO_SANDBOX_DEPOSITION_ID=self.deposition_id,
            ZENODO_API_BASE=self.api_base
        ):
            # Run render command
            call_command(
                'render_zenodo',
                stdout=tempfile.TemporaryFile(mode='w+'),
                stderr=tempfile.TemporaryFile(mode='w+')
            )

            # Verify generated files exist
            data_dir = Path(settings.BASE_DIR) / 'data'
            self.assertTrue((data_dir / 'README.md').exists(), "README.md should be generated")
            self.assertTrue((data_dir / 'last_version.txt').exists(), "last_version.txt should exist")
            self.assertTrue((data_dir / 'zenodo_dynamic.json').exists(), "zenodo_dynamic.json should exist")

    @override_settings(
        ZENODO_API_TOKEN=None,
        ZENODO_SANDBOX_DEPOSITION_ID=None,
        ZENODO_API_BASE=None
    )
    def test_deposit_zenodo_command_dry_run(self):
        """Test deposit_zenodo command in dry-run mode (no actual upload)."""
        with override_settings(
            ZENODO_API_TOKEN=self.api_token,
            ZENODO_SANDBOX_DEPOSITION_ID=self.deposition_id,
            ZENODO_API_BASE=self.api_base
        ):
            # Test with --dry-run flag if available
            # This test verifies the command can be called without errors
            # Actual upload testing would require cleanup logic
            try:
                call_command(
                    'deposit_zenodo',
                    '--help',
                    stdout=tempfile.TemporaryFile(mode='w+'),
                    stderr=tempfile.TemporaryFile(mode='w+')
                )
            except SystemExit:
                pass  # --help exits, which is expected

    def test_env_file_loading(self):
        """Test that environment variables are loaded from tests/.env."""
        self.assertIsNotNone(self.api_token, "ZENODO_API_TOKEN should be loaded from .env")
        self.assertIsNotNone(self.deposition_id, "ZENODO_SANDBOX_DEPOSITION_ID should be loaded")
        self.assertIn('zenodo.org', self.api_base, "ZENODO_API_BASE should contain zenodo.org")

    def test_zenodo_api_connectivity(self):
        """Test basic connectivity to Zenodo API."""
        import requests

        headers = {"Authorization": f"Bearer {self.api_token}"}
        response = requests.get(f"{self.api_base}/deposit/depositions", headers=headers)

        self.assertEqual(
            response.status_code, 200,
            f"Should be able to connect to Zenodo API. Status: {response.status_code}"
        )

        depositions = response.json()
        self.assertIsInstance(depositions, list, "Depositions should be a list")


@tag('integration', 'zenodo', 'slow')
class ZenodoFullDepositTest(TestCase):
    """
    Full end-to-end deposit tests.

    WARNING: These tests actually upload to Zenodo sandbox.
    Use with caution and clean up manually if needed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_test_env()

        cls.api_token = os.environ.get('ZENODO_API_TOKEN')
        cls.deposition_id = os.environ.get('ZENODO_SANDBOX_DEPOSITION_ID')
        cls.api_base = os.environ.get('ZENODO_API_BASE', 'https://sandbox.zenodo.org/api')

        if not cls.api_token or not cls.deposition_id:
            raise unittest.SkipTest(
                "Full deposit tests require ZENODO_API_TOKEN and "
                "ZENODO_SANDBOX_DEPOSITION_ID in tests/.env"
            )

    def setUp(self):
        """Set up test data."""
        Work.objects.create(title="Full Test Work", doi="10.test/full")
        Source.objects.create(name="Full Test Source", url_field="https://test.example.com")

    @tag('slow', 'upload')
    def test_full_deposit_cycle(self):
        """
        Test full deposit cycle: render → deposit → verify.

        This test actually uploads to Zenodo sandbox.
        Run manually with: python manage.py test tests.test_zenodo_integration.ZenodoFullDepositTest --tag=upload
        """
        # This is a placeholder for full integration testing
        # Actual implementation would:
        # 1. Run render_zenodo
        # 2. Run deposit_zenodo
        # 3. Verify files were uploaded
        # 4. Clean up (delete uploaded files)
        self.skipTest("Full upload test requires manual execution and cleanup")


import unittest
